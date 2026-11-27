#!/usr/bin/env python3
"""QuestionBridge 0.16: ILIAS QTI choice, Kprim, Long Menu, numerical, matching, cloze, essay and keyword text questions to Moodle XML."""
import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from fractions import Fraction
import base64
import copy
import html
import json
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


CLOZE_FORBIDDEN = set('{}~#\\/"%<>&')


@dataclass
class ClozeGap:
    kind: str
    weight: int = 0
    answers: tuple = ()
    correct: str = ""
    shuffle: bool = False
    case_sensitive: bool = False
    target: Decimal = Decimal(0)
    tolerance: Decimal = Decimal(0)


@dataclass
class ClozeQuestion:
    title: str
    parts: list


def cloze_value(value, title):
    require(value and not (set(value) & CLOZE_FORBIDDEN),
            f"{title}: Sonderzeichen oder leerer Wert in einer Luecke "
            "werden nicht unterstuetzt.")
    return value


def read_cloze_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Lueckentext-Struktur."
    rating = meta.get("textgaprating")
    require(rating in {"ci", "cs"},
            f"{title}: Textluecken-Bewertung {rating!r} wird nicht unterstuetzt.")
    require((meta.get("combinations") or "") in {"", "W10="}
            and not (meta.get("identicalScoring") or "").strip("0"),
            f"{title}: Kombinationen oder identische Bewertung werden nicht unterstuetzt.")

    def dec(text):
        text = (text or "").strip()
        require(re.fullmatch(r"[+-]?[0-9]{1,9}(?:[.][0-9]{1,6})?", text),
                f"{title}: Nicht unterstuetzter Dezimalwert: {text!r}.")
        return Decimal(text)

    presentation = item.find("presentation")
    require(presentation is not None and len(presentation) == 1, error)
    flow = presentation.find("flow")
    require(flow is not None and len(flow) >= 2 and flow[0].tag == "material", error)

    parts, gaps, bounds = [], {}, {}
    for index, child in enumerate(flow):
        if child.tag == "material":
            nodes = child.findall("mattext")
            require(len(child) == 1 and len(nodes) == 1, error)
            text = plain(nodes[0])
            require("{" not in text and "}" not in text,
                    f"{title}: Geschweifte Klammern im Text werden nicht unterstuetzt.")
            parts.append(html.escape(text, quote=False).replace("\n", "<br>")
                         + ("<br>" if index == 0 else ""))
            continue
        ident = child.get("ident")
        require(child.tag in {"response_str", "response_num"} and ident
                and ident not in gaps and len(child) == 1
                and child.get("rcardinality") == "Single", error)
        render = child[0]
        if child.tag == "response_str" and render.tag == "render_fib":
            require(len(render) == 0 and render.get("fibtype", "String") == "String", error)
            gap = ClozeGap("text", case_sensitive=(rating == "cs"))
        elif child.tag == "response_str" and render.tag == "render_choice":
            labels = render.findall("response_label")
            require(len(labels) >= 2 and len(labels) == len(render)
                    and render.get("shuffle", "No") in {"Yes", "No"}, error)
            options = []
            for label in labels:
                nodes = label.findall("./material/mattext")
                require(len(nodes) == 1 and len(label) == 1, error)
                options.append(cloze_value(plain(nodes[0]), title))
            require(len(set(options)) == len(options), f"{title}: Doppelte Auswahloption.")
            gap = ClozeGap("choice", answers=tuple(options),
                           shuffle=render.get("shuffle") == "Yes")
        elif (child.tag == "response_num" and render.tag == "render_fib"
              and render.get("fibtype") == "Decimal" and len(render) == 0):
            gap = ClozeGap("numeric")
            bounds[ident] = (dec(render.get("minnumber")), dec(render.get("maxnumber")))
        else:
            require(False, error)
        gaps[ident] = gap
        parts.append(gap)
    require(gaps, f"{title}: Keine Luecken gefunden.")

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1
            and all(c.tag in {"outcomes", "respcondition"} for c in blocks[0]), error)
    rules = {}
    for rule in blocks[0].findall("respcondition"):
        tags = [c.tag for c in rule]
        require(rule.get("continue", "Yes") == "Yes"
                and tags in (["conditionvar", "setvar"],
                             ["conditionvar", "setvar", "displayfeedback"]), error)
        condition, scoring = rule[0], rule[1]
        require(len(condition) == 1 and condition[0].tag == "varequal"
                and set(condition[0].attrib) == {"respident"}
                and condition[0].get("respident") in gaps, error)
        require(scoring.get("action") == "Add"
                and scoring.get("varname", "SCORE") == "SCORE"
                and set(scoring.attrib) <= {"action", "varname"}, error)
        score = Decimal((scoring.text or "").strip())
        require(score.is_finite() and score == score.to_integral_value()
                and 0 <= score <= 1000,
                f"{title}: Punkte pro Luecke muessen ganzzahlig sein.")
        rules.setdefault(condition[0].get("respident"), []).append(
            ((condition[0].text or "").strip(), int(score)))
    for entry in item.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Lueckentext wird noch nicht unterstuetzt.")

    for ident, gap in gaps.items():
        entries = rules.get(ident, [])
        require(entries, f"{title}: Luecke {ident} ohne Bewertungsregel.")
        if gap.kind == "text":
            scores = {score for _, score in entries}
            texts = [cloze_value(text, title) for text, _ in entries]
            score = next(iter(scores))
            require(len(scores) == 1 and score > 0,
                    f"{title}: Textluecke {ident}: ungleiche oder fehlende Punkte "
                    "werden nicht unterstuetzt.")
            require(len(set(texts)) == len(texts), f"{title}: Doppelte Loesung in {ident}.")
            gap.answers, gap.weight = tuple(texts), score
        elif gap.kind == "choice":
            by_text = dict(entries)
            require(len(by_text) == len(entries) and set(by_text) == set(gap.answers), error)
            positive = [text for text, score in by_text.items() if score > 0]
            require(len(positive) == 1,
                    f"{title}: Auswahlluecke {ident} braucht genau eine richtige Antwort.")
            gap.correct, gap.weight = positive[0], by_text[positive[0]]
        else:
            require(len(entries) == 1, error)
            text, score = entries[0]
            target = dec(text)
            lower, upper = bounds[ident]
            require(score > 0 and lower <= target <= upper
                    and target - lower == upper - target,
                    f"{title}: Numerische Luecke {ident} braucht positive Punkte und "
                    "einen symmetrischen Bereich um den Sollwert.")
            gap.target, gap.tolerance, gap.weight = target, upper - target, score
    return ClozeQuestion(title, parts)


def cloze_markup(question):
    out = []
    for part in question.parts:
        if isinstance(part, str):
            out.append(part)
            continue
        if part.kind == "text":
            tag = "SHORTANSWER_C" if part.case_sensitive else "SHORTANSWER"
            body = "~".join("=" + answer for answer in part.answers)
        elif part.kind == "choice":
            tag = "MULTICHOICE_S" if part.shuffle else "MULTICHOICE"
            body = "~".join(("=" if option == part.correct else "") + option
                            for option in part.answers)
        else:
            tag = "NUMERICAL"
            body = f"={format(part.target, 'f')}:{format(part.tolerance, 'f')}"
        out.append("{%d:%s:%s}" % (part.weight, tag, body))
    return "".join(out)


def cloze_points(question):
    return sum(part.weight for part in question.parts if not isinstance(part, str))


@dataclass
class EssayQuestion:
    title: str
    text: str
    points: Decimal


def read_essay_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Freitext-Struktur."
    require(meta.get("wordcounter") == "0",
            f"{title}: Wortzaehler wird nicht unterstuetzt.")
    require(meta.get("matchcondition") == "0" and meta.get("termrelation") == "non"
            and meta.get("termscoring") == "YTowOnt9",
            f"{title}: Stichwortbewertung wird nicht unterstuetzt.")
    require(meta.get("specificfeedback") == "non",
            f"{title}: Feedback bei Freitext wird noch nicht unterstuetzt.")

    presentation = item.find("presentation")
    require(presentation is not None and len(presentation) == 1, error)
    flow = presentation.find("flow")
    require(flow is not None and [c.tag for c in flow] == ["material", "response_str"],
            error)
    material, response = flow
    nodes = material.findall("mattext")
    require(len(material) == 1 and len(nodes) == 1, error)
    prompt = plain(nodes[0])
    require(response.attrib == {"ident": "TEXT", "rcardinality": "Ordered"}
            and len(response) == 1, error)
    render = response[0]
    require(render.tag == "render_fib" and render.get("fibtype") == "String"
            and set(render.attrib) <= {"fibtype", "prompt"}
            and len(render) == 1 and render[0].tag == "response_label"
            and render[0].attrib == {"ident": "A"} and len(render[0]) == 0, error)

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1 and blocks[0].get("scoremodel") == "HumanRater",
            f"{title}: Nur manuelle Bewertung wird unterstuetzt.")
    require([c.tag for c in blocks[0]] == ["outcomes", "respcondition"], error)
    outcomes, rule = blocks[0]
    require([c.tag for c in outcomes] == ["decvar"], error)
    variable = outcomes[0]
    require(len(variable) == 0 and variable.get("varname") == "WritingScore"
            and variable.get("vartype") == "Integer"
            and variable.get("minvalue") == "0"
            and set(variable.attrib) <= {"varname", "vartype", "minvalue", "maxvalue"},
            error)
    maximum = (variable.get("maxvalue") or "").strip()
    require(re.fullmatch(r"[0-9]{1,6}(?:[.][0-9]{1,3})?", maximum)
            and Decimal(maximum) > 0, f"{title}: Ungueltige Maximalpunktzahl.")
    require([c.tag for c in rule] == ["conditionvar"]
            and [c.tag for c in rule[0]] == ["other"]
            and (rule[0][0].text or "").strip() == "tutor_rated", error)
    require(not item.findall("itemfeedback"),
            f"{title}: Feedback bei Freitext wird noch nicht unterstuetzt.")
    return EssayQuestion(title, prompt, Decimal(maximum))


TERM_PATTERN = re.compile(
    r'i:(\d+);O:\d+:"ASS_AnswerMultipleResponseImage":6:\{'
    r's:\d+:"\x00\*\x00answertext";s:(\d+):"(.*?)";'
    r's:\d+:"\x00\*\x00points";s:\d+:"([0-9]{1,6})";'
    r's:\d+:"\x00\*\x00order";i:\d+;'
    r's:\d+:"\x00\*\x00id";i:-?\d+;'
    r's:\d+:"points_unchecked";N;'
    r's:\d+:"image";N;\}', re.S)


@dataclass
class KeywordQuestion:
    title: str
    text: str
    points: Decimal
    mode: str
    terms: list
    case_sensitive: bool


def read_terms(encoded, title):
    error = f"{title}: Stichwortbewertung kann nicht gelesen werden."
    try:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise ValueError(error)
    head = re.match(r"a:(\d+):\{", raw)
    require(head is not None and int(head.group(1)) <= 50, error)
    position, terms = head.end(), []
    for index in range(int(head.group(1))):
        match = TERM_PATTERN.match(raw, position)
        require(match is not None and int(match.group(1)) == index, error)
        text = match.group(3)
        require(len(text.encode("utf-8")) == int(match.group(2)), error)
        terms.append((text, Decimal(match.group(4))))
        position = match.end()
    require(raw[position:] == "}", error)
    return terms


def terms_overlap(a, b):
    if a in b or b in a:
        return True
    return any(a.endswith(b[:k]) or b.endswith(a[:k])
               for k in range(1, min(len(a), len(b)) + 1))


def read_keyword_question(item, title, meta):
    terms = read_terms(meta.get("termscoring") or "", title)
    require(terms, f"{title}: Stichwortbewertung ohne Begriffe wird nicht unterstuetzt.")
    mode = meta.get("termrelation")
    require(mode in {"one", "all", "any"} and meta.get("specificfeedback") == mode,
            f"{title}: Stichwortmodus {mode!r} wird nicht unterstuetzt.")
    rating = meta.get("textrating")
    require(rating in {"ci", "cs"},
            f"{title}: Textvergleich {rating!r} wird nicht unterstuetzt.")

    clone = copy.deepcopy(item)
    for entry in clone.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Freitext wird noch nicht unterstuetzt.")
        clone.remove(entry)
    essay = read_essay_question(clone, title, dict(
        meta, termrelation="non", termscoring="YTowOnt9", specificfeedback="non"))

    texts = [text for text, _ in terms]
    for text in texts:
        require(text and text == text.strip() and not (set(text) & set("*\\\r\n")),
                f"{title}: Sonderzeichen in Begriffen werden nicht unterstuetzt.")
    folded = [text.lower() for text in texts]
    require(len(set(folded)) == len(folded), f"{title}: Doppelte Begriffe.")
    points = [value for _, value in terms]
    unsupported = f"{title}: Punkte pro Begriff werden in diesem Modus nicht unterstuetzt."
    if mode == "one":
        require(len(terms) <= 20 and not any(points), unsupported)
    else:
        require(len(terms) == 2,
                f"{title}: In diesem Modus werden genau zwei Begriffe unterstuetzt.")
        require(not terms_overlap(*folded),
                f"{title}: Sich ueberlappende Begriffe werden nicht unterstuetzt.")
        if mode == "all":
            require(not any(points), unsupported)
        else:
            require(all(value > 0 for value in points) and sum(points) == essay.points,
                    f"{title}: Begriffspunkte muessen sich zur Maximalpunktzahl addieren.")
    return KeywordQuestion(title, essay.text, essay.points, mode, terms, rating == "cs")


def keyword_answers(question):
    texts = [text for text, _ in question.terms]
    if question.mode == "one":
        return [(f"*{text}*", "100") for text in texts]
    first, second = texts
    both = [(f"*{first}*{second}*", "100"), (f"*{second}*{first}*", "100")]
    if question.mode == "all":
        return both
    total = sum(value for _, value in question.terms)
    return both + [(f"*{text}*", answer_fraction(value, total, question.title))
                   for text, value in question.terms]


@dataclass
class KprimQuestion:
    title: str
    text: str
    statements: list
    points: Decimal
    shuffle: bool


def kprim_value(node, title):
    value = (node.text or "").strip()
    require(len(node) == 0 and value in {"0", "1"},
            f"{title}: Kprim-Bewertung wird nur als alles-oder-nichts unterstuetzt.")
    return value == "1"


def read_kprim_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Kprim-Struktur."
    scoring_error = f"{title}: Kprim-Bewertung wird nur als alles-oder-nichts unterstuetzt."
    answer_type = meta.get("answer_type")
    require(answer_type == "singleLine",
            f"{title}: Kprim-Antworttyp {answer_type!r} wird nicht unterstuetzt.")
    labels_setting = meta.get("option_label_setting")
    require(labels_setting == "right_wrong",
            f"{title}: Kprim-Beschriftung {labels_setting!r} wird nicht unterstuetzt "
            "(nur right_wrong).")

    presentation = item.find("presentation")
    require(presentation is not None, error)
    prompts = presentation.findall("./flow/material/mattext")
    groups = presentation.findall("./flow/response_lid")
    require(len(prompts) == 1 and len(groups) == 1, error)
    prompt = plain(prompts[0])
    group = groups[0]
    require(group.get("ident") and group.get("rcardinality") == "Multiple", error)
    render = group.find("render_choice")
    require(render is not None and len(group) == 1
            and len(render.findall("response_label")) == len(render), error)
    shuffle = render.get("shuffle", "No")
    require(shuffle in {"Yes", "No"}, "Unbekannte Mischoption.")
    labels = render.findall("response_label")
    require(len(labels) >= 2, f"{title}: Mindestens zwei Aussagen erforderlich.")
    texts = {}
    for label in labels:
        key = label.get("ident")
        nodes = label.findall("./material/mattext")
        require(key and key not in texts and len(nodes) == 1 and len(label) == 1
                and set(label.attrib) == {"ident"}, error)
        text = plain(nodes[0])
        require(text.strip(), f"{title}: Leere Kprim-Aussage.")
        texts[key] = text

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1 and blocks[0].get("scoremodel") is None
            and all(c.tag in {"outcomes", "respcondition"} for c in blocks[0]), error)
    outcomes = blocks[0].findall("outcomes")
    require(len(outcomes) == 1 and [c.tag for c in outcomes[0]] == ["decvar"]
            and outcomes[0][0].get("varname", "SCORE") == "SCORE", error)

    each, all_rules, none_rules = {}, [], []
    for rule in blocks[0].findall("respcondition"):
        require(rule.get("continue", "Yes") == "Yes"
                and rule.find("conditionvar") is not None
                and [c.tag for c in rule][0] == "conditionvar"
                and len(rule[0]) == 1, error)
        term = rule[0][0]
        if term.tag == "varequal":
            require([c.tag for c in rule] == ["conditionvar", "displayfeedback"]
                    and set(term.attrib) == {"respident"}
                    and term.get("respident") in texts
                    and term.get("respident") not in each, error)
            each[term.get("respident")] = kprim_value(term, title)
        elif term.tag == "and":
            all_rules.append(rule)
        elif term.tag == "or":
            none_rules.append(rule)
        else:
            require(False, scoring_error)
    require(len(all_rules) == 1 and len(none_rules) == 1, scoring_error)
    all_rule, none_rule = all_rules[0], none_rules[0]
    require([c.tag for c in all_rule] == ["conditionvar", "setvar"]
            and [c.tag for c in none_rule] == ["conditionvar", "setvar"], scoring_error)

    all_term, none_term = all_rule[0][0], none_rule[0][0]
    require(len(all_term) == len(texts) and len(none_term) == len(texts)
            and all(t.tag == "varequal" and set(t.attrib) == {"respident"}
                    for t in all_term)
            and all(t.tag == "not" and not t.attrib and len(t) == 1
                    and t[0].tag == "varequal" and set(t[0].attrib) == {"respident"}
                    for t in none_term), scoring_error)
    all_values = {t.get("respident"): kprim_value(t, title) for t in all_term}
    none_values = {t[0].get("respident"): kprim_value(t[0], title) for t in none_term}
    require(set(all_values) == set(texts) and len(all_values) == len(texts)
            and none_values == all_values, scoring_error)
    require(each == all_values, f"{title}: Kprim-Loesung ist widerspruechlich.")

    def points(rule):
        scoring = rule.find("setvar")
        value = (scoring.text or "").strip()
        require(scoring.get("action") == "Add"
                and scoring.get("varname", "SCORE") == "SCORE"
                and set(scoring.attrib) <= {"action", "varname"}
                and re.fullmatch(r"[0-9]{1,6}(?:[.][0-9]{1,3})?", value), scoring_error)
        return Decimal(value)

    full = points(all_rule)
    require(full > 0 and points(none_rule) == 0, scoring_error)
    maximum = outcomes[0][0].get("maxvalue")
    if maximum is not None:
        require(re.fullmatch(r"[0-9]{1,6}(?:[.][0-9]{1,3})?", maximum.strip())
                and Decimal(maximum.strip()) == full,
                f"{title}: Kprim-Maximalpunktzahl passt nicht zur Bewertung.")

    for entry in item.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Kprim wird noch nicht unterstuetzt.")
    return KprimQuestion(title, prompt, [(texts[k], each[k]) for k in texts],
                         full, shuffle == "Yes")


def kprim_html(text):
    return "<p>" + html.escape(text, quote=False).replace("\n", "<br>") + "</p>"


LONGMENU_PLACEHOLDER = re.compile(r"\[Longmenu ([0-9]+)\]")


def read_longmenu_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Long-Menu-Struktur."
    try:
        types = json.loads(meta.get("gapTypes") or "")
    except ValueError:
        types = None
    require(isinstance(types, list) and types
            and all(type(t) is int and t in (0, 1) for t in types),
            f"{title}: Long-Menu-Lueckentyp wird nicht unterstuetzt.")
    require((meta.get("identical_scoring") or "").strip() in {"", "0"},
            f"{title}: Identische Bewertung wird bei Long Menu nicht unterstuetzt.")

    presentation = item.find("presentation")
    require(presentation is not None and len(presentation) == 1, error)
    flow = presentation.find("flow")
    require(flow is not None and len(flow) == 2 + len(types)
            and [c.tag for c in flow] == ["material", "material"] + ["response_str"] * len(types),
            error)
    parts_text = []
    for material in flow[:2]:
        nodes = material.findall("mattext")
        require(len(material) == 1 and len(nodes) == 1, error)
        text = plain(nodes[0])
        require("{" not in text and "}" not in text,
                f"{title}: Geschweifte Klammern im Text werden nicht unterstuetzt.")
        parts_text.append(text)
    prompt, gap_text = parts_text

    numbers = LONGMENU_PLACEHOLDER.findall(gap_text)
    require(numbers == [str(n) for n in range(1, len(types) + 1)],
            f"{title}: Platzhalter [Longmenu n] passen nicht zu den Luecken.")

    options = {}
    for number, response in enumerate(flow[2:], 1):
        ident = f"LongMenu_{number}"
        require(response.attrib == {"ident": ident, "rcardinality": "Single"}
                and len(response) >= 1
                and all(c.tag == "response_label" for c in response), error)
        values = []
        for label in response:
            nodes = label.findall("./material/fieldentry")
            require(len(nodes) == 1 and len(label) == 1 and len(label[0]) == 1
                    and set(label.attrib) == {"ident"}, error)
            value = nodes[0].text or ""
            require(value.strip(), f"{title}: Leere Antwortoption in Luecke {number}.")
            values.append(value)
        require(len(set(values)) == len(values),
                f"{title}: Doppelte Antwortoption in Luecke {number}.")
        options[ident] = values

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1 and all(c.tag in {"outcomes", "respcondition"} for c in blocks[0]),
            error)
    outcomes = blocks[0].findall("outcomes")
    require(len(outcomes) == 1 and [c.tag for c in outcomes[0]] == ["decvar"], error)
    scores = {}
    for rule in blocks[0].findall("respcondition"):
        require(rule.get("continue", "Yes") == "Yes"
                and [c.tag for c in rule] == ["conditionvar", "setvar", "displayfeedback"]
                and len(rule[0]) == 1, error)
        term, scoring = rule[0][0], rule[1]
        require(term.tag == "varequal" and set(term.attrib) == {"respident"}
                and term.get("respident") in options, error)
        require(scoring.get("action") == "Add"
                and scoring.get("varname", "SCORE") == "SCORE"
                and set(scoring.attrib) <= {"action", "varname"}, error)
        score = Decimal((scoring.text or "").strip())
        require(score.is_finite() and score == score.to_integral_value()
                and 0 <= score <= 1000,
                f"{title}: Punkte pro Luecke muessen ganzzahlig sein.")
        key = (term.get("respident"), term.text or "")
        require(key[1] in options[key[0]] and key not in scores, error)
        scores[key] = int(score)
    require(len(scores) == sum(len(v) for v in options.values()),
            f"{title}: Antwortoption ohne Bewertungsregel.")
    for entry in item.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Long Menu wird noch nicht unterstuetzt.")

    gaps = []
    for number, kind in enumerate(types, 1):
        ident = f"LongMenu_{number}"
        positive = [(o, scores[(ident, o)]) for o in options[ident] if scores[(ident, o)] > 0]
        require(positive, f"{title}: Luecke {number} hat keine richtige Antwort.")
        require(len({s for _, s in positive}) == 1,
                f"{title}: Luecke {number}: ungleiche Punkte der richtigen Antworten "
                "werden nicht unterstuetzt.")
        weight = positive[0][1]
        if kind == 0:
            require(len(positive) == 1,
                    f"{title}: Auswahlluecke {number} braucht genau eine richtige Antwort.")
            all_options = tuple(cloze_value(o, title) for o in options[ident])
            gaps.append(ClozeGap("choice", weight=weight, answers=all_options,
                                 correct=positive[0][0], shuffle=False))
        else:
            gaps.append(ClozeGap("text", weight=weight, case_sensitive=True,
                                 answers=tuple(cloze_value(o, title) for o, _ in positive)))

    def clean(text):
        return html.escape(text, quote=False).replace("\n", "<br>")

    parts = [clean(prompt) + "<br>"]
    position = 0
    for match, gap in zip(LONGMENU_PLACEHOLDER.finditer(gap_text), gaps):
        parts.append(clean(gap_text[position:match.start()]))
        parts.append(gap)
        position = match.end()
    parts.append(clean(gap_text[position:]))
    return ClozeQuestion(title, parts)


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
        if questiontype == "assClozeTest":
            questions.append(read_cloze_question(item, title, meta))
            continue
        if questiontype == "assTextQuestion":
            if meta.get("termrelation") == "non":
                questions.append(read_essay_question(item, title, meta))
            else:
                questions.append(read_keyword_question(item, title, meta))
            continue
        if questiontype == "assLongMenu":
            questions.append(read_longmenu_question(item, title, meta))
            continue
        if questiontype == "assKprimChoice":
            questions.append(read_kprim_question(item, title, meta))
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
        if isinstance(src, KeywordQuestion):
            q = ET.SubElement(quiz, "question", type="shortanswer")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="plain_text")
            ET.SubElement(body, "text").text = src.text
            ET.SubElement(q, "defaultgrade").text = format(src.points, "f")
            ET.SubElement(q, "penalty").text = "0"
            ET.SubElement(q, "usecase").text = "1" if src.case_sensitive else "0"
            for text, fraction in keyword_answers(src):
                answer = ET.SubElement(q, "answer", fraction=fraction, format="plain_text")
                ET.SubElement(answer, "text").text = text
            continue
        if isinstance(src, EssayQuestion):
            q = ET.SubElement(quiz, "question", type="essay")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="plain_text")
            ET.SubElement(body, "text").text = src.text
            ET.SubElement(q, "defaultgrade").text = format(src.points, "f")
            ET.SubElement(q, "penalty").text = "0"
            ET.SubElement(q, "responseformat").text = "plain"
            ET.SubElement(q, "responserequired").text = "1"
            ET.SubElement(q, "responsefieldlines").text = "15"
            ET.SubElement(q, "attachments").text = "0"
            ET.SubElement(q, "attachmentsrequired").text = "0"
            continue
        if isinstance(src, ClozeQuestion):
            q = ET.SubElement(quiz, "question", type="cloze")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="html")
            ET.SubElement(body, "text").text = cloze_markup(src)
            ET.SubElement(q, "defaultgrade").text = str(cloze_points(src))
            ET.SubElement(q, "penalty").text = "0"
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
        if isinstance(src, KprimQuestion):
            q = ET.SubElement(quiz, "question", type="kprime")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="html")
            ET.SubElement(body, "text").text = kprim_html(src.text)
            general = ET.SubElement(q, "generalfeedback", format="html")
            ET.SubElement(general, "text").text = ""
            ET.SubElement(q, "defaultgrade").text = format(src.points, "f")
            ET.SubElement(q, "penalty").text = "0"
            ET.SubElement(q, "hidden").text = "0"
            ET.SubElement(ET.SubElement(q, "scoringmethod"), "text").text = "kprimeonezero"
            ET.SubElement(q, "shuffleanswers").text = "true" if src.shuffle else "false"
            ET.SubElement(q, "numberofrows").text = str(len(src.statements))
            ET.SubElement(q, "numberofcolumns").text = "2"
            for number, (text, _) in enumerate(src.statements, 1):
                row = ET.SubElement(q, "row", number=str(number))
                option = ET.SubElement(row, "optiontext", format="html")
                ET.SubElement(option, "text").text = kprim_html(text)
                feedback = ET.SubElement(row, "feedbacktext", format="html")
                ET.SubElement(feedback, "text").text = ""
            for number, label in enumerate(("Richtig", "Falsch"), 1):
                column = ET.SubElement(q, "column", number=str(number))
                response = ET.SubElement(column, "responsetext", format="moodle_auto_format")
                ET.SubElement(response, "text").text = label
            for number, (_, right) in enumerate(src.statements, 1):
                for column, value in ((1, right), (2, not right)):
                    weight = ET.SubElement(q, "weight", rownumber=str(number),
                                           columnnumber=str(column))
                    ET.SubElement(weight, "value").text = "1.000" if value else "0.000"
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
            if isinstance(q, KeywordQuestion):
                print(f"OK: {q.title}: SHORTANSWER ({q.mode}), {len(q.terms)} Begriffe, "
                      f"{q.points} Punkt(e)")
                continue
            if isinstance(q, EssayQuestion):
                print(f"OK: {q.title}: ESSAY, {q.points} Punkt(e), manuelle Bewertung")
                continue
            if isinstance(q, ClozeQuestion):
                gap_count = sum(1 for part in q.parts if not isinstance(part, str))
                print(f"OK: {q.title}: CLOZE, {gap_count} Luecken, "
                      f"{cloze_points(q)} Punkt(e)")
                continue
            if isinstance(q, MatchingQuestion):
                print(f"OK: {q.title}: MATCH, {len(q.pairs)} Paare, "
                      f"{q.points * len(q.pairs)} Punkt(e)")
                continue
            if isinstance(q, KprimQuestion):
                print(f"OK: {q.title}: KPRIM, {len(q.statements)} Aussagen, "
                      f"{q.points} Punkt(e), alles-oder-nichts")
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
