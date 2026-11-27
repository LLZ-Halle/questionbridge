#!/usr/bin/env python3
"""QuestionBridge prototype: restricted ILIAS QTI 1.2 single choice to Moodle XML."""
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
        require(meta.get("QUESTIONTYPE") == "assSingleChoice", f"{title}: Kein unterstuetzter Single-Choice-Typ.")
        presentation = item.find("presentation")
        require(presentation is not None, f"{title}: Darstellung fehlt.")
        response = presentation.findall(".//response_lid")
        require(len(response) == 1 and response[0].get("rcardinality") == "Single", f"{title}: Genau eine Einfachauswahl erwartet.")
        prompts = presentation.findall("./flow/material/mattext")
        require(len(prompts) == 1, f"{title}: Unbekannte Fragetextstruktur.")
        prompt = plain(prompts[0])
        render = response[0].find("render_choice")
        require(render is not None, f"{title}: Antwortliste fehlt.")
        require(render.get("shuffle", "No") in {"Yes", "No"}, "Unbekannte Mischoption.")
        labels = render.findall("response_label")
        require(len(labels) >= 2, f"{title}: Mindestens zwei Antworten erforderlich.")
        scores = {}
        processing = item.find("resprocessing")
        require(processing is not None, "Bewertung fehlt.")
        require(all(c.tag in {"outcomes", "respcondition"} for c in processing), "Unbekannte Bewertungsstruktur.")
        for cond in processing.findall("respcondition"):
            require(cond.get("continue", "Yes") == "Yes", "Nicht unterstuetzte Bewertungssteuerung.")
            cv = cond.find("conditionvar")
            require(cv is not None and len(cv) == 1 and cv[0].tag == "varequal", "Komplexe Bewertungsbedingungen werden nicht unterstuetzt.")
            eq = cv[0]
            require(eq.get("respident") == response[0].get("ident"), "Bewertung verweist auf unbekannte Antwortgruppe.")
            sets = cond.findall("setvar")
            require(len(sets) == 1 and sets[0].get("action") == "Add", "Nicht unterstuetzte Punkteberechnung.")
            require(sets[0].get("varname", "SCORE") == "SCORE", "Unbekannte Bewertungsvariable.")
            key = (eq.text or "").strip()
            require(key not in scores, "Mehrere Bewertungsregeln pro Antwort.")
            score = Decimal((sets[0].text or "").strip())
            require(score.is_finite() and score >= 0, "Ungueltige oder negative Punktzahl.")
            scores[key] = score
        answers = []
        for label in labels:
            key = label.get("ident")
            require(key is not None and key in scores, "Antwort ohne Bewertungsregel.")
            texts = label.findall("./material/mattext")
            require(len(texts) == 1, "Unbekannte Antwortstruktur.")
            answers.append(Answer(key, plain(texts[0]), scores[key]))
        require(len({a.ident for a in answers}) == len(answers), "Doppelte Antwortkennung.")
        require(set(scores) == {a.ident for a in answers}, "Bewertung fuer unbekannte Antwort.")
        require(sum(a.score > 0 for a in answers) == 1, f"{title}: Genau eine Antwort muss positive Punkte haben; Teilpunkte werden nicht unterstuetzt.")
        require(not any((t.text or "").strip() for t in item.findall(".//itemfeedback//mattext")), "Feedback wird in Version 0.1 noch nicht unterstuetzt.")
        questions.append(Question(title, prompt, answers, render.get("shuffle") == "Yes"))
    return questions

def write_moodle(questions, path):
    quiz = ET.Element("quiz")
    for src in questions:
        q = ET.SubElement(quiz, "question", type="multichoice")
        ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
        ET.SubElement(ET.SubElement(q, "questiontext", format="plain_text"), "text").text = src.text
        ET.SubElement(q, "defaultgrade").text = str(max(a.score for a in src.answers))
        ET.SubElement(q, "penalty").text = "0"
        ET.SubElement(q, "single").text = "true"
        ET.SubElement(q, "shuffleanswers").text = "1" if src.shuffle else "0"
        ET.SubElement(q, "answernumbering").text = "abc"
        for answer in src.answers:
            a = ET.SubElement(q, "answer", fraction="100" if answer.score > 0 else "0", format="plain_text")
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
            print(f"OK: {q.title}: {len(q.answers)} Antworten, {max(a.score for a in q.answers)} Punkt(e)")
        print(f"Exportiert: {len(questions)} Frage(n). Quelle unveraendert.")
        return 0
    except (ValueError, OSError, ET.ParseError, InvalidOperation) as exc:
        print(f"ABBRUCH: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
