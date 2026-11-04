"""High-precision prompt-injection rules for English and Vietnamese (DECISIONS §9, Layer 0).

Text is folded before matching: NFKC, zero-width characters removed, lower
case, Vietnamese diacritics removed (``đ`` becomes ``d``) and runs of spaces
collapsed, so "Bỏ qua các hướng dẫn trước đó" and "bo qua cac huong dan truoc
do" match the same rule. A rule hit is a ``block`` verdict.

The rules cover requests to ignore or replace earlier instructions, to reveal
the system prompt or hidden context, role-play as the system or developer,
and fake prompt boundaries: chat-template tokens of common models and closing
tags of the api's own prompt sections.

This file uses the standard library only, because the LiteLLM gateway keeps a
byte-identical copy as ``infra/litellm/callbacks/screening_rules.py`` (it
cannot import ``apps/api``); a test fails when the two copies differ. The
gateway skips the ``template_tag`` rule because the api's own prompts contain
those tags around untrusted content.

Change a rule by editing both copies and raising ``RULES_VERSION``.
"""

from dataclasses import dataclass
import re
import unicodedata

RULES_VERSION = "rules-v1"

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))


def fold(text: str) -> str:
    """The text the rules match: NFKC, lower case, no diacritics, single spaces, lines kept."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    text = text.replace("đ", "d").replace("Đ", "D")
    text = "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char)).lower()
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]


def _rule(rule_id: str, pattern: str) -> Rule:
    return Rule(rule_id, re.compile(pattern, re.MULTILINE))


# English: an override verb, an optional determiner, a word for "earlier", then a word for instructions.
_EN_OVERRIDE = (
    r"\b(?:ignore|disregard|forget|skip|bypass|override|overrule|drop)\b"
    r"(?: (?:all|any|every|each|the|your|these|those|of|everything|that))*"
    r" (?:previous|prior|above|earlier|preceding|original|initial|old|system|developer|existing|given)\b"
    r"(?: \w+){0,2} (?:instructions?|prompts?|rules|directions|directives|guidelines|guidance|context|messages?|orders|constraints)\b"
)
_EN_NEW_RULES = (
    r"\b(?:your|the) (?:new|real|actual|updated) (?:instructions?|rules|task|system prompt) (?:are|is)\b"
)
_EN_REVEAL = (
    r"\b(?:reveal|show|print|display|output|repeat|recite|tell me|give me|send me|leak|dump|share|expose|what (?:is|are|was|were))\b"
    r"(?: \w+){0,3} (?:your|the|its|any) (?:full |complete |entire |exact |original )?"
    r"(?:system|hidden|initial|original|secret|internal|developer|base) "
    r"(?:prompts?|instructions?|messages?|rules|context|configuration|guidelines)\b"
)
_EN_SYSTEM_PROMPT = r"\bsystem prompts?\b"
_EN_REPEAT_ABOVE = (
    r"\b(?:repeat|print|output|copy|echo|recite)\b(?: \w+){0,3} (?:everything|all|the text|the words|the lines|whatever)"
    r" (?:above|before this|written above|you were (?:given|told))\b"
)
_EN_ROLEPLAY = (
    r"\b(?:act|behave|pretend|roleplay|role-play|role play|pose|respond|speak)\b(?: \w+){0,2} (?:as|like|to be|you are)"
    r" (?:the |a |an |my )?(?:system|developer|admin|administrator|root|superuser|dan|jailbroken|unrestricted|unfiltered|uncensored)\b"
)
_EN_YOU_ARE_NOW = (
    r"\byou are (?:now|no longer)\b(?: \w+){0,2} (?:dan|jailbroken|unrestricted|unfiltered|uncensored|free|the system|the developer|an? (?:ai|assistant|model) (?:without|with no))\b"
)
_EN_MODE = (
    r"\b(?:enable|activate|enter|switch to|turn on|start)\b (?:the )?(?:developer|god|dan|jailbreak|jailbroken|unrestricted|admin|sudo) mode\b"
)

# Vietnamese, folded: an override verb, a word for instructions, then a word for "earlier" or "system".
_VI_OVERRIDE = (
    r"\b(?:bo qua|phot lo|lo di|quen di|quen het|quen|khong (?:can )?tuan theo|dung tuan theo|vo hieu hoa|huy bo|bat chap)\b"
    r"(?: (?:moi|tat ca|toan bo|cac|nhung|het|di))* (?:huong dan|chi dan|chi thi|menh lenh|lenh|quy tac|nguyen tac|loi nhac|prompt|rang buoc)\b"
    r"(?: \w+){0,2} (?:truoc|truoc do|o tren|phia tren|ben tren|tren|ban dau|goc|he thong|cu|da cho|duoc giao)\b"
)
_VI_NEW_RULES = r"\b(?:huong dan|chi dan|nhiem vu|quy tac) (?:moi|that su|thuc su) cua (?:ban|may) (?:la|nhu sau)\b"
_VI_REVEAL = (
    r"\b(?:tiet lo|cho (?:toi|minh|tao|em|anh) (?:xem|biet)|in ra|hien thi|hien ra|liet ke|nhac lai|lap lai|xuat ra|dua ra|gui|chia se|viet ra|doc)\b"
    r"(?: \w+){0,3} (?:prompt he thong|loi nhac he thong|cau lenh he thong|"
    r"(?:chi dan|huong dan|chi thi|quy tac|cau hinh|ngu canh) (?:he thong|an|goc|ban dau|bi mat|noi bo))\b"
)
_VI_SYSTEM_PROMPT = r"\b(?:prompt he thong|loi nhac he thong)\b"
_VI_ROLEPLAY = (
    r"\b(?:dong vai|gia vo (?:la|lam)|gia lam|hanh dong nhu|hanh xu nhu|tra loi nhu)\b(?: (?:la|mot|nguoi))*"
    r" (?:he thong|nha phat trien|lap trinh vien|quan tri vien|admin|developer|system|dan|ai khong gioi han)\b"
)
_VI_MODE = (
    r"\b(?:bat|kich hoat|chuyen sang|vao|mo)\b (?:che do) (?:nha phat trien|developer|dan|jailbreak|khong gioi han|quan tri|admin|god)\b"
)

# Chat-template tokens of common models, and section headers written to look like one.
_MODEL_TOKENS = (
    r"<\|(?:im_start|im_end|im_sep|system|user|assistant|endoftext|begin_of_text|end_of_text|start_header_id|end_header_id|eot_id)\|>"
    r"|\[/?inst\]|<</?sys>>|<start_of_turn>|<end_of_turn>"
)
_FAKE_HEADER = r"^(?:#{2,}|\[|<)\s*(?:system|developer|instructions?|new instructions?)\s*(?:\]|>|:)?\s*$|^(?:system|developer)\s*:"
# Closing or opening tags of the sections the api's prompts put untrusted content in.
_TEMPLATE_TAG = r"</?\s*(?:question|message|history|document|documents|context|rows|data|spec|system|instructions?|user|assistant)\s*>"

RULES: tuple[Rule, ...] = (
    _rule("en_override", _EN_OVERRIDE),
    _rule("en_new_rules", _EN_NEW_RULES),
    _rule("en_reveal", _EN_REVEAL),
    _rule("en_system_prompt", _EN_SYSTEM_PROMPT),
    _rule("en_repeat_above", _EN_REPEAT_ABOVE),
    _rule("en_roleplay", _EN_ROLEPLAY),
    _rule("en_you_are_now", _EN_YOU_ARE_NOW),
    _rule("en_mode", _EN_MODE),
    _rule("vi_override", _VI_OVERRIDE),
    _rule("vi_new_rules", _VI_NEW_RULES),
    _rule("vi_reveal", _VI_REVEAL),
    _rule("vi_system_prompt", _VI_SYSTEM_PROMPT),
    _rule("vi_roleplay", _VI_ROLEPLAY),
    _rule("vi_mode", _VI_MODE),
    _rule("model_token", _MODEL_TOKENS),
    _rule("fake_header", _FAKE_HEADER),
    _rule("template_tag", _TEMPLATE_TAG),
)
RULE_IDS = tuple(rule.id for rule in RULES)
# Rules the gateway skips because the api's own prompts trip them.
GATEWAY_SKIPPED = frozenset({"template_tag"})


def match(text: str, skip: frozenset[str] = frozenset()) -> list[str]:
    """The ids of the rules ``text`` trips, in rule order; ``skip`` leaves rules out."""
    folded = fold(text)
    return [rule.id for rule in RULES if rule.id not in skip and rule.pattern.search(folded)]
