#!/usr/bin/env python3
"""QuestionBridge 0.11: ILIAS QTI choice, numerical and 1:1 matching questions to Moodle XML."""
import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from fractions import Fraction
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

@dataclass
class Answer:
    ident: str
    text: str
    score: Decimal
    feedback: str = ""

@dataclass
class Question:
    title: str
    text: str
    answers: list
    shuffle: bool
    single: bool
    correct_feedback: str = ""
    incomplete_feedback: str = ""

def require(ok, message):
    if not ok:
        raise ValueError(message)

def plain(node):
    require(node is not None, "Text fehlt.")
    require(node.get("texttype", "text/plain") == "text/plain", "Nur einfacher Text wird unterstuetzt.")
    require(len(node) == 0, "Verschachtelte Textinhalte werden nicht unterstuetzt.")
    return node.text or ""

def read_input(path):
    path = Path(path)
    if path.suffix.lower() != ".zip":
        return path.read_bytes()

    limit = 10 * 1024 * 1024
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [
                entry for entry in archive.infolist()
                if not entry.is_dir()
                and re.fullmatch(
                    r".+__qti_.+\.xml",
                    entry.filename.rsplit("/", 1)[-1],
                    re.IGNORECASE,
                )
            ]
            if len(candidates) != 1:
                raise SystemExit(
                    f"{path.name}: Genau eine QTI-XML erwartet, "
                    f"{len(candidates)} gefunden."
                )

            entry = candidates[0]
            if entry.file_size > limit:
                raise SystemExit(f"{path.name}: QTI-XML ist groesser als 10 MiB.")
            with archive.open(entry) as handle:
                raw = handle.read(limit + 1)
            if len(raw) > limit:
                raise SystemExit(f"{path.name}: QTI-XML ist groesser als 10 MiB.")
            return raw
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SystemExit(f"{path.name}: ZIP konnte nicht gelesen werden: {exc}")


GRADE_TEXT = "0 5 10 12.5 20 25 30 40 50 60 70 75 80 90 100".split()
GRADE_XML = {Fraction(t): t for t in GRADE_TEXT}
GRADE_XML.update({-Fraction(t): "-" + t for t in GRADE_TEXT if t != "0"})


def max_points(answers, single):
    positive = [a.score for a in answers if a.score > 0]
    if not positive:
        return Decimal(0)
    if single:
        return max(positive)
    # Sum decimal input exactly, independently of the decimal context.
    parts = [p.as_tuple() for p in positive]
    scale = min(p.exponent for p in parts)
    units = sum(int(''.join(map(str, p.digits))) * 10 ** (p.exponent - scale)
                for p in parts)
    return Decimal((0, tuple(map(int, str(units))), scale))


def answer_fraction(score, total, title):
    weight = 100 * Fraction(score) / Fraction(total)
    require(weight in GRADE_XML,
            f"{title}: Antwortgewicht {weight}% wird nicht exakt unterstuetzt.")
    return GRADE_XML[weight]


RESULT_FEEDBACK = {
    "response_allcorrect": False,
    "response_onenotcorrect": True,
}


def read_mc_result_rule(cv, respident, incomplete, title):
    terms = {}
    error = f"{title}: Nicht unterstuetzte MC-Ergebnisfeedback-Bedingung."
    require(len(cv) > 0, error)
    for index, term in enumerate(cv):
        if incomplete and index > 0:
            require(term.tag == "or" and len(term) == 1 and not term.attrib,
                    error)
            term = term[0]
        selected = term.tag != "not"
        if not selected:
            require(len(term) == 1 and not term.attrib, error)
            term = term[0]
        require(term.tag == "varequal" and len(term) == 0
                and term.attrib == {"respident": respident}, error)
        key = (term.text or "").strip()
        require(key and key not in terms, error)
        terms[key] = selected
    return terms


def read_answer_feedback(item, processing, title, result_rules):
    by_id = {}
    for entry in item.findall("itemfeedback"):
        ident = entry.get("ident")
        nodes = entry.findall("./flow_mat/material/mattext")
        require(ident and ident not in by_id,
                f"{title}: Fehlende oder doppelte Feedback-Kennung.")
        require(len(nodes) == 1 and list(entry.iter("mattext")) == nodes,
                f"{title}: Nicht unterstuetzte Feedback-Struktur.")
        text = plain(nodes[0])
        by_id[ident] = text if text.strip() else ""

    by_answer = {}
    used = set(result_rules)
    for ref in result_rules:
        require(ref in by_id, f"{title}: Unbekannte Feedback-Referenz: {ref!r}.")
    for condition in processing.findall("respcondition"):
        for link in condition.findall("displayfeedback"):
            selected = condition.find("conditionvar/varequal")
            ref = link.get("linkrefid")
            require(ref in by_id, f"{title}: Unbekannte Feedback-Referenz: {ref!r}.")
            if ref in RESULT_FEEDBACK:
                require(ref in result_rules and not condition.findall("setvar"),
                        f"{title}: Ergebnisfeedback in einer Bewertungsregel.")
                continue
            if not by_id[ref]:
                continue
            require(selected is not None and link.get("feedbacktype") == "Response",
                    f"{title}: Nur Feedback bei Auswahl einer Antwort wird unterstuetzt.")
            answer_id = (selected.text or "").strip()
            require(answer_id not in by_answer,
                    f"{title}: Mehrere Feedbacktexte fuer dieselbe Antwort.")
            by_answer[answer_id] = by_id[ref]
            used.add(ref)

    require(all(not text or ref in used for ref, text in by_id.items()),
            f"{title}: Nicht zugeordnetes Feedback wird nicht unterstuetzt.")
    return by_answer, {ref: by_id[ref] for ref in result_rules}


@dataclass
class NumericalQuestion:
    title: str
    text: str
    score: Decimal
    target: Decimal
    tolerance: Decimal


def read_numerical_question(item, title):
    error = f"{title}: Nicht unterstuetzte numerische QTI-Struktur."

    def tags(node):
        return [child.tag for child in node]

    def number(node):
        text = (node.text or "").strip()
        require(len(node) == 0
                and re.fullmatch(r"[+-]?[0-9]{1,9}(?:[.][0-9]{1,6})?", text),
                f"{title}: Nicht unterstuetzter Dezimalwert: {text!r}.")
        return Decimal(text)

    presentations = item.findall("presentation")
    require(len(presentations) == 1 and tags(presentations[0]) == ["flow"], error)
    flow = presentations[0][0]
    require(tags(flow) == ["material", "response_num"], error)
    material, response = flow
    require(tags(material) == ["mattext"], error)
    prompt = plain(material[0])

    ident = response.get("ident")
    require(bool(ident) and response.attrib == {
        "ident": ident, "rcardinality": "Single", "numtype": "Decimal",
    } and tags(response) == ["render_fib"], error)
    render = response[0]
    require(len(render) == 0 and render.get("fibtype") == "Decimal"
            and set(render.attrib) <= {"fibtype", "maxchars"}, error)

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1 and tags(blocks[0]) == ["outcomes", "respcondition"],
            error)
    outcomes, rule = blocks[0]
    require(tags(outcomes) == ["decvar"] and len(outcomes[0]) == 0
            and not outcomes[0].attrib, error)
    require(rule.get("continue", "Yes") == "Yes"
            and tags(rule) == ["conditionvar", "setvar", "displayfeedback"], error)
    condition, scoring, link = rule
    require(tags(condition) == ["vargte", "varlte"]
            and all(bound.attrib == {"respident": ident} for bound in condition),
            error)
    lower, upper = map(number, condition)
    require(lower <= upper, f"{title}: Untergrenze liegt ueber der Obergrenze.")
    require(scoring.get("action") == "Add"
            and scoring.get("varname", "SCORE") == "SCORE"
            and set(scoring.attrib) <= {"action", "varname"}, error)
    score = number(scoring)
    require(score > 0, f"{title}: Numerische Frage braucht positive Punkte.")

    entries = item.findall("itemfeedback")
    require(link.attrib == {"feedbacktype": "Response", "linkrefid": "Correct"}
            and len(entries) == 1 and entries[0].get("ident") == "Correct",
            error)
    feedback = entries[0]
    require(tags(feedback) == ["flow_mat"]
            and tags(feedback[0]) == ["material"]
            and tags(feedback[0][0]) == ["mattext"]
            and not plain(feedback[0][0][0]).strip(),
            f"{title}: Numerisches Feedback mit Text wird noch nicht unterstuetzt.")

    return NumericalQuestion(title, prompt, score,
                             (lower + upper) / 2, (upper - lower) / 2)


@dataclass
class MatchingQuestion:
    title: str
    text: str
    pairs: list
    points: Decimal
    shuffle: bool


def read_matching_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Zuordnungsstruktur."
    mode = meta.get("matching_mode")
    require(mode == "1:1",
            f"{title}: Zuordnungsmodus {mode!r} wird nicht unterstuetzt (nur 1:1).")

    presentation = item.find("presentation")
    require(presentation is not None, error)
    prompts = presentation.findall("./flow/material/mattext")
    groups = presentation.findall("./flow/response_grp")
    require(len(prompts) == 1 and len(groups) == 1, error)
    prompt = plain(prompts[0])
    group = groups[0]
    ident = group.get("ident")
    require(ident and group.get("rcardinality") == "Multiple", error)
    render = group.find("render_choice")
    require(render is not None and len(group) == 1
            and len(render.findall("response_label")) == len(render), error)
    shuffle = render.get("shuffle", "No")
    require(shuffle in {"Yes", "No"}, "Unbekannte Mischoption.")

    definitions, terms, term_groups = {}, {}, []
    for label in render.findall("response_label"):
        key = label.get("ident")
        texts = label.findall("./material/mattext")
        require(key and len(texts) == 1 and len(label) == 1
                and set(label.attrib) <= {"ident", "match_max", "match_group"}, error)
        require(key not in definitions and key not in terms,
                f"{title}: Doppelte Antwortkennung.")
        text = plain(texts[0])
        require(text.strip(), f"{title}: Leerer Zuordnungstext.")
        if "match_group" in label.attrib or "match_max" in label.attrib:
            require(label.get("match_max") == "1" and label.get("match_group"), error)
            term_groups.append(set(label.get("match_group").split(",")))
            terms[key] = text
        else:
            definitions[key] = text
    require(all(g == set(definitions) for g in term_groups), error)

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1
            and all(c.tag in {"outcomes", "respcondition"} for c in blocks[0]), error)
    feedback_ids = {e.get("ident") for e in item.findall("itemfeedback")}
    pairs, scores = [], []
    seen_definitions, seen_terms = set(), set()
    for rule in blocks[0].findall("respcondition"):
        require(rule.get("continue", "Yes") == "Yes"
                and [c.tag for c in rule] == ["conditionvar", "setvar", "displayfeedback"],
                error)
        condition, scoring, link = rule
        require(len(condition) == 1 and condition[0].tag == "varsubset"
                and condition[0].attrib == {"respident": ident}, error)
        parts = [part.strip() for part in (condition[0].text or "").split(",")]
        require(len(parts) == 2 and parts[0] in definitions and parts[1] in terms, error)
        require(parts[0] not in seen_definitions and parts[1] not in seen_terms,
                f"{title}: Mehrfachzuordnungen werden nicht unterstuetzt.")
        require(scoring.get("action") == "Add"
                and scoring.get("varname", "SCORE") == "SCORE"
                and set(scoring.attrib) <= {"action", "varname"}, error)
        score = Decimal((scoring.text or "").strip())
        require(score.is_finite() and len(score.as_tuple().digits) <= 30
                and abs(score.as_tuple().exponent) <= 30,
                f"{title}: Ungueltige Punktzahl oder zu viele Stellen.")
        require(link.get("linkrefid") in feedback_ids, error)
        seen_definitions.add(parts[0])
        seen_terms.add(parts[1])
        pairs.append((definitions[parts[0]], terms[parts[1]]))
        scores.append(score)

    require(len(pairs) >= 2 and seen_definitions == set(definitions)
            and seen_terms == set(terms),
            f"{title}: Jede Definition und jeder Term braucht genau ein Paar.")
    require(len(set(scores)) == 1,
            f"{title}: Zuordnung abgebrochen, da ungleiche Punkte pro Paar "
            "nicht unterstuetzt werden.")
    require(scores[0] > 0, f"{title}: Punkte pro Paar muessen positiv sein.")
    for entry in item.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Zuordnungsfragen wird noch nicht unterstuetzt.")
    return MatchingQuestion(title, prompt, pairs, scores[0], shuffle == "Yes")


def read_questions(path):
    raw = read_input(path)
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
        if questiontype == "assNumeric":
            questions.append(read_numerical_question(item, title))
            continue
        if questiontype == "assMatchingQuestion":
            questions.append(read_matching_question(item, title, meta))
            continue
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
        result_rules = {}
        for cond in processing.findall("respcondition"):
            require(cond.get("continue", "Yes") == "Yes", "Nicht unterstuetzte Bewertungssteuerung.")
            require(all(c.tag in {"conditionvar", "setvar", "displayfeedback"} for c in cond)
                    and len(cond.findall("conditionvar")) == 1,
                    "Unbekannte Bewertungsstruktur.")
            cv = cond.find("conditionvar")
            sets = cond.findall("setvar")
            if single or sets:
                require(len(cv) == 1,
                        "Komplexe Bewertungsbedingungen werden nicht unterstuetzt.")
            if not sets:
                links = cond.findall("displayfeedback")
                require(len(links) == 1,
                        f"{title}: Genau ein Verweis fuer Ergebnisfeedback erwartet.")
                link = links[0]
                ref = link.get("linkrefid")
                require(ref in RESULT_FEEDBACK and ref not in result_rules
                        and link.get("feedbacktype") == "Response",
                        f"{title}: Unbekannte oder doppelte Ergebnisfeedback-Regel.")
                if not single:
                    result_rules[ref] = read_mc_result_rule(
                        cv, response[0].get("ident"), RESULT_FEEDBACK[ref], title)
                    continue
                condition = cv[0]
                if RESULT_FEEDBACK[ref]:
                    require(condition.tag == "not" and len(condition) == 1,
                            f"{title}: Nichtauswahl der richtigen Antwort erwartet.")
                    eq = condition[0]
                else:
                    eq = condition
                require(eq.tag == "varequal" and len(eq) == 0
                        and eq.get("respident") == response[0].get("ident"),
                        f"{title}: Unbekannte Bedingung fuer Ergebnisfeedback.")
                result_rules[ref] = (eq.text or "").strip()
                continue
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
            require(len(sets) == 1 and sets[0].get("action") == "Add", "Nicht unterstuetzte Punkteberechnung.")
            require(sets[0].get("varname", "SCORE") == "SCORE", "Unbekannte Bewertungsvariable.")
            key = (eq.text or "").strip()
            destination = unselected_scores if unselected else scores
            require(key not in destination,
                    "Mehrere Bewertungsregeln pro Antwort und Auswahlzustand.")
            score = Decimal((sets[0].text or "").strip())
            require(score.is_finite() and len(score.as_tuple().digits) <= 30
                    and abs(score.as_tuple().exponent) <= 30,
                    "Ungueltige Punktzahl oder zu viele Stellen.")
            if unselected:
                require(score == 0,
                        "Punkte fuer Nichtauswahl werden noch nicht unterstuetzt.")
            destination[key] = score
        feedback_by_answer, result_texts = read_answer_feedback(
            item, processing, title, result_rules)
        answers = []
        for label in labels:
            key = label.get("ident")
            require(key is not None and key in scores, "Antwort ohne Bewertungsregel.")
            texts = label.findall("./material/mattext")
            require(len(texts) == 1, "Unbekannte Antwortstruktur.")
            answers.append(Answer(key, plain(texts[0]), scores[key],
                                  feedback_by_answer.get(key, "")))
        require(len({a.ident for a in answers}) == len(answers), "Doppelte Antwortkennung.")
        require(set(scores) == {a.ident for a in answers}, "Bewertung fuer unbekannte Antwort.")
        if not single:
            require(set(unselected_scores) == {a.ident for a in answers},
                    "Fuer jede MC-Antwort wird eine Nichtauswahl-Regel erwartet.")
        total = max_points(answers, single)
        require(total > 0, f"{title}: Mindestens eine positive Antwort erforderlich.")
        for answer in answers:
            answer_fraction(answer.score, total, title)
        if result_rules and not single:
            require(all(a.score != 0 for a in answers),
                    f"{title}: MC-Ergebnisfeedback mit Null-Punkte-Antwort "
                    "wird nicht unterstuetzt.")
            for ref, terms in result_rules.items():
                incomplete = RESULT_FEEDBACK[ref]
                expected = {
                    a.ident: (a.score > 0) != incomplete for a in answers
                }
                require(terms == expected,
                        f"{title}: MC-Ergebnisfeedback passt nicht zur Bewertung: {ref}.")
        if result_rules and single:
            full_credit = {a.ident for a in answers if a.score == total}
            require(len(full_credit) == 1
                    and all({key} == full_credit for key in result_rules.values()),
                    f"{title}: Ergebnisfeedback muss auf die einzige Antwort "
                    "mit voller Punktzahl verweisen.")
        questions.append(Question(
            title, prompt, answers, render.get("shuffle") == "Yes", single,
            result_texts.get("response_allcorrect", ""),
            result_texts.get("response_onenotcorrect", ""),
        ))
    return questions

def write_moodle(questions, path):
    quiz = ET.Element("quiz")
    for src in questions:
        if isinstance(src, NumericalQuestion):
            q = ET.SubElement(quiz, "question", type="numerical")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="plain_text")
            ET.SubElement(body, "text").text = src.text
            ET.SubElement(q, "defaultgrade").text = format(src.score, "f")
            ET.SubElement(q, "penalty").text = "0"
            answer = ET.SubElement(q, "answer", fraction="100")
            ET.SubElement(answer, "text").text = format(src.target, "f")
            ET.SubElement(answer, "tolerance").text = format(src.tolerance, "f")
            continue
        if isinstance(src, MatchingQuestion):
            q = ET.SubElement(quiz, "question", type="matching")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="plain_text")
            ET.SubElement(body, "text").text = src.text
            ET.SubElement(q, "defaultgrade").text = format(src.points * len(src.pairs), "f")
            ET.SubElement(q, "penalty").text = "0"
            ET.SubElement(q, "shuffleanswers").text = "1" if src.shuffle else "0"
            for definition, term in src.pairs:
                sub = ET.SubElement(q, "subquestion", format="plain_text")
                ET.SubElement(sub, "text").text = definition
                ET.SubElement(ET.SubElement(sub, "answer"), "text").text = term
            continue
        q = ET.SubElement(quiz, "question", type="multichoice")
        ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
        ET.SubElement(ET.SubElement(q, "questiontext", format="plain_text"), "text").text = src.text
        total = max_points(src.answers, src.single)
        ET.SubElement(q, "defaultgrade").text = format(total, "f")
        ET.SubElement(q, "penalty").text = "0"
        ET.SubElement(q, "single").text = "true" if src.single else "false"
        ET.SubElement(q, "shuffleanswers").text = "1" if src.shuffle else "0"
        ET.SubElement(q, "answernumbering").text = "abc"
        for tag, text in (
            ("correctfeedback", src.correct_feedback),
            ("partiallycorrectfeedback", src.incomplete_feedback),
            ("incorrectfeedback", src.incomplete_feedback),
        ):
            if text:
                field = ET.SubElement(q, tag, format="plain_text")
                ET.SubElement(field, "text").text = text
        for answer in src.answers:
            fraction = answer_fraction(answer.score, total, src.title)
            a = ET.SubElement(q, "answer", fraction=fraction, format="plain_text")
            ET.SubElement(a, "text").text = answer.text
            if answer.feedback:
                feedback = ET.SubElement(a, "feedback", format="plain_text")
                ET.SubElement(feedback, "text").text = answer.feedback
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
            if isinstance(q, NumericalQuestion):
                print(f"OK: {q.title}: NUM, {q.score} Punkt(e)")
                continue
            if isinstance(q, MatchingQuestion):
                print(f"OK: {q.title}: MATCH, {len(q.pairs)} Paare, "
                      f"{q.points * len(q.pairs)} Punkt(e)")
                continue
            kind = "SC" if q.single else "MC"
            total = max_points(q.answers, q.single)
            print(f"OK: {q.title}: {kind}, {len(q.answers)} Antworten, {total} Punkt(e)")
        print(f"Exportiert: {len(questions)} Frage(n). Quelle unveraendert.")
        return 0
    except (ValueError, OSError, ET.ParseError, InvalidOperation) as exc:
        print(f"ABBRUCH: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
