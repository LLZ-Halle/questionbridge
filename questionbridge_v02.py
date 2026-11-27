#!/usr/bin/env python3
"""QuestionBridge 0.2: restricted ILIAS QTI single/multiple choice to Moodle XML."""
import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

@dataclass
class Answer:
    ident: str
    text: str
    score: Decimal

@dataclass
class Question:
    title: str
    text: str
    answers: list
    shuffle: bool
    single: bool

def require(ok, message):
    if not ok:
        raise ValueError(message)

def plain(node):
    require(node is not None, "Text fehlt.")
    require(node.get("texttype", "text/plain") == "text/plain", "Nur einfacher Text wird unterstuetzt.")
    require(len(node) == 0, "Verschachtelte Textinhalte werden nicht unterstuetzt.")
    return node.text or ""

def read_questions(path):
    raw = Path(path).read_bytes()
    require(len(raw) <= 5_000_000, "Datei groesser als 5 MB.")
    text = raw.decode("utf-8-sig")
    require("<!ENTITY" not in text.upper(), "XML-Entities sind nicht erlaubt.")
    text = re.sub(r'<!DOCTYPE\s+questestinterop\s+SYSTEM\s+"ims_qtiasiv1p2p1.dtd"\s*>', '', text)
    require("<!DOCTYPE" not in text.upper(), "Unbekannte DTD: Import abgebrochen.")
    root = ET.fromstring(text)
    require(root.tag == "questestinterop", "Erwartet wird eine ILIAS-QTI-Datei ohne XML-Namespace.")
    require(not any(e.tag in {"matimage", "mataudio", "matvideo", "matref"} for e in root.iter()), "Medien werden noch nicht unterstuetzt.")
    items = list(root.iter("item"))
    require(items, "Keine Fragen gefunden.")
    questions = []
    for item in items:
        title = item.get("title", "").strip()
        require(title, "Fragentitel fehlt.")
        meta = {f.findtext("fieldlabel"): f.findtext("fieldentry") for f in item.findall("./itemmetadata/qtimetadata/qtimetadatafield")}
        questiontype = meta.get("QUESTIONTYPE")
        require(questiontype in {"assSingleChoice", "assMultipleChoice"},
                f"{title}: Nicht unterstuetzter Fragetyp.")
        single = questiontype == "assSingleChoice"
        presentation = item.find("presentation")
        require(presentation is not None, f"{title}: Darstellung fehlt.")
        response = presentation.findall(".//response_lid")
        cardinality = "Single" if single else "Multiple"
        require(len(response) == 1 and
                response[0].get("rcardinality") == cardinality,
                f"{title}: Unerwartete Antwortgruppe.")
        prompts = presentation.findall("./flow/material/mattext")
        require(len(prompts) == 1, f"{title}: Unbekannte Fragetextstruktur.")
        prompt = plain(prompts[0])
        render = response[0].find("render_choice")
        require(render is not None, f"{title}: Antwortliste fehlt.")
        require(render.get("shuffle", "No") in {"Yes", "No"}, "Unbekannte Mischoption.")
        labels = render.findall("response_label")
        require(len(labels) >= 2, f"{title}: Mindestens zwei Antworten erforderlich.")
        scores = {}
        unselected_scores = {}
        processing = item.find("resprocessing")
        require(processing is not None, "Bewertung fehlt.")
        require(all(c.tag in {"outcomes", "respcondition"} for c in processing), "Unbekannte Bewertungsstruktur.")
        for cond in processing.findall("respcondition"):
            require(cond.get("continue", "Yes") == "Yes", "Nicht unterstuetzte Bewertungssteuerung.")
            cv = cond.find("conditionvar")
            require(cv is not None and len(cv) == 1,
                    "Komplexe Bewertungsbedingungen werden nicht unterstuetzt.")
            condition = cv[0]
            unselected = condition.tag == "not"
            if unselected:
                require(not single and len(condition) == 1 and
                        condition[0].tag == "varequal",
                        "Nicht unterstuetzte Nichtauswahl-Bedingung.")
                eq = condition[0]
            else:
                require(condition.tag == "varequal",
                        "Nicht unterstuetzte Bewertungsbedingung.")
                eq = condition
            require(eq.get("respident") == response[0].get("ident"), "Bewertung verweist auf unbekannte Antwortgruppe.")
            sets = cond.findall("setvar")
            require(len(sets) == 1 and sets[0].get("action") == "Add", "Nicht unterstuetzte Punkteberechnung.")
            require(sets[0].get("varname", "SCORE") == "SCORE", "Unbekannte Bewertungsvariable.")
            key = (eq.text or "").strip()
            destination = unselected_scores if unselected else scores
            require(key not in destination,
                    "Mehrere Bewertungsregeln pro Antwort und Auswahlzustand.")
            score = Decimal((sets[0].text or "").strip())
            require(score.is_finite() and score >= 0,
                    "Ungueltige oder negative Punktzahl.")
            if unselected:
                require(score == 0,
                        "Punkte fuer Nichtauswahl werden noch nicht unterstuetzt.")
            destination[key] = score
        answers = []
        for label in labels:
            key = label.get("ident")
            require(key is not None and key in scores, "Antwort ohne Bewertungsregel.")
            texts = label.findall("./material/mattext")
            require(len(texts) == 1, "Unbekannte Antwortstruktur.")
            answers.append(Answer(key, plain(texts[0]), scores[key]))
        require(len({a.ident for a in answers}) == len(answers), "Doppelte Antwortkennung.")
        require(set(scores) == {a.ident for a in answers}, "Bewertung fuer unbekannte Antwort.")
        positive = [a.score for a in answers if a.score > 0]
        if single:
            require(len(positive) == 1,
                    f"{title}: Genau eine richtige Antwort erwartet.")
        else:
            require(set(unselected_scores) == {a.ident for a in answers},
                    "Fuer jede MC-Antwort wird eine Nichtauswahl-Regel erwartet.")
            require(len(positive) == 2 and positive[0] == positive[1],
                    f"{title}: MC unterstuetzt vorerst genau zwei gleich bewertete richtige Antworten.")
        require(not any((t.text or "").strip() for t in item.findall(".//itemfeedback//mattext")), "Feedback wird in Version 0.1 noch nicht unterstuetzt.")
        questions.append(Question(title, prompt, answers,
                                  render.get("shuffle") == "Yes", single))
    return questions

def write_moodle(questions, path):
    quiz = ET.Element("quiz")
    for src in questions:
        q = ET.SubElement(quiz, "question", type="multichoice")
        ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
        ET.SubElement(ET.SubElement(q, "questiontext", format="plain_text"), "text").text = src.text
        total = sum(a.score for a in src.answers)
        ET.SubElement(q, "defaultgrade").text = str(total)
        ET.SubElement(q, "penalty").text = "0"
        ET.SubElement(q, "single").text = "true" if src.single else "false"
        ET.SubElement(q, "shuffleanswers").text = "1" if src.shuffle else "0"
        ET.SubElement(q, "answernumbering").text = "abc"
        for answer in src.answers:
            fraction = ("100" if src.single else "50") if answer.score > 0 else "0"
            a = ET.SubElement(q, "answer", fraction=fraction, format="plain_text")
            ET.SubElement(a, "text").text = answer.text
    ET.indent(quiz, space="  ")
    ET.ElementTree(quiz).write(path, encoding="utf-8", xml_declaration=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        require(args.source.resolve() != args.destination.resolve(), "Quelle und Ziel muessen verschieden sein.")
        require(not args.destination.exists(), "Zieldatei existiert bereits; anderen Namen verwenden.")
        questions = read_questions(args.source)
        write_moodle(questions, args.destination)
        for q in questions:
            kind = "SC" if q.single else "MC"
            total = sum(a.score for a in q.answers)
            print(f"OK: {q.title}: {kind}, {len(q.answers)} Antworten, {total} Punkt(e)")
        print(f"Exportiert: {len(questions)} Frage(n). Quelle unveraendert.")
        return 0
    except (ValueError, OSError, ET.ParseError, InvalidOperation) as exc:
        print(f"ABBRUCH: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
