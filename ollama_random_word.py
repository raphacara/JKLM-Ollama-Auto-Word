import json
import random
import re
import shutil
import subprocess
import string
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple


OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:3b-instruct-q3_K_M"
DEFAULT_LEXICAL_THEME = "libre"
DEFAULT_LANGUAGE = "fr"
LANGUAGE_RULES = {
    "fr": {
        "label": "francais",
        "setup": (
            "Tu proposes des mots francais. "
            "A chaque demande, tu dois repondre avec exactement un seul mot francais, "
            "sans article, sans determinant, sans ponctuation, sans phrase, sans explication. "
            "Les verbes conjugues sont autorises s'ils existent reellement en francais. "
            "Le mot doit contenir exactement la suite de lettres demandee, dans le meme ordre, "
            "de facon consecutive. Si c'est impossible, reponds seulement: impossible."
        ),
        "theme": (
            " Bonus seulement: si possible, choisis un mot lie au champ lexical suivant: {theme}. "
            "N'insiste pas sur ce theme si cela empeche de trouver un vrai mot valide."
        ),
        "base": (
            "Trouve un mot francais existant et jouable qui contient exactement la suite de lettres '{sequence}'. "
            "Reponds avec un seul mot, sans ponctuation, sans article. "
            "Les verbes conjugues existants sont autorises."
        ),
        "retry": "Reessaie avec un autre mot vraiment different de tous les precedents.",
    },
    "en": {
        "label": "anglais",
        "setup": (
            "You propose English words. "
            "For each request, reply with exactly one real English word, "
            "without punctuation, without explanation, without a full sentence. "
            "Conjugated verbs are allowed if they are real English forms. "
            "The word must contain exactly the requested letter sequence, in the same order, consecutively. "
            "If impossible, reply only: impossible."
        ),
        "theme": (
            " Bonus only: if possible, choose a word related to this semantic field: {theme}. "
            "Do not force the theme if it prevents finding a valid real word."
        ),
        "base": (
            "Find one real playable English word that contains exactly the letter sequence '{sequence}'. "
            "Reply with exactly one word, no punctuation, no article."
        ),
        "retry": "Try again with a truly different word from the previous attempts.",
    },
    "es": {
        "label": "espagnol",
        "setup": (
            "Tu propones palabras en espanol. "
            "En cada solicitud debes responder con exactamente una palabra real en espanol, "
            "sin puntuacion, sin explicacion y sin frase completa. "
            "Los verbos conjugados estan permitidos si existen de verdad en espanol. "
            "La palabra debe contener exactamente la secuencia de letras pedida, en el mismo orden y consecutiva. "
            "Si es imposible, responde solo: imposible."
        ),
        "theme": (
            " Solo como bonus: si es posible, elige una palabra relacionada con este campo semantico: {theme}. "
            "No fuerces el tema si eso impide encontrar una palabra valida."
        ),
        "base": (
            "Encuentra una palabra real y jugable en espanol que contenga exactamente la secuencia '{sequence}'. "
            "Responde con una sola palabra, sin puntuacion y sin articulo."
        ),
        "retry": "Intenta otra vez con una palabra realmente diferente de las anteriores.",
    },
    "la": {
        "label": "latin",
        "setup": (
            "Tu propones verba Latina. "
            "In unaquaque petitione responde cum uno solo verbo Latino vero, "
            "sine punctuatione, sine explicatione, sine sententia plena. "
            "Formae flexae admittuntur si vere Latinae sunt. "
            "Verbum debet continere exacte seriem litterarum petitam, eodem ordine et continue. "
            "Si impossibile est, responde tantum: impossible."
        ),
        "theme": (
            " Solum ut bonus: si fieri potest, elige verbum ad hunc campum semanticum pertinens: {theme}. "
            "Noli urgere thema si id impedit quominus verum verbum validum invenias."
        ),
        "base": (
            "Inveni unum verbum Latinum verum et ludibile quod exacte continet seriem litterarum '{sequence}'. "
            "Responde cum uno solo verbo, sine punctuatione."
        ),
        "retry": "Conare iterum cum verbo vere diverso ab omnibus prioribus.",
    },
}
MAX_ATTEMPTS = 30
HTTP_TIMEOUT = 60
GENERATOR_OPTIONS = {"temperature": 0.65, "top_p": 0.92, "repeat_penalty": 1.2}
ARTICLE_PREFIXES = ("l'", "d'", "j'", "t'", "m'", "n'", "s'", "c'", "qu'")
ARTICLES = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "du",
    "de",
    "deux",
    "au",
    "aux",
}
ATTEMPT_FLAVORS = [
    "Prends un mot courant.",
    "Prends un mot plutot soutenu.",
    "Prends un mot concret, pas un nom propre.",
    "Prends un mot simple et clairement francais.",
    "Prends un mot different des essais precedents.",
    "Prends un mot qui sonne naturel dans une partie de BombParty.",
]
SUSPICIOUS_PATTERNS = (
    "phém",
    "émm",
    "éhm",
    "ôph",
    "xh",
    "yh",
    "qj",
    "wj",
)


def ollama_generate(
    prompt: str,
    model: str,
    context: Optional[List[int]] = None,
    options: Optional[dict] = None,
) -> Tuple[str, List[int]]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
    }
    if context:
        payload["context"] = context
    if options:
        payload["options"] = options

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    parts = []
    next_context = context or []
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                chunk = json.loads(line)
                if "response" in chunk:
                    parts.append(chunk["response"])
                if "context" in chunk:
                    next_context = chunk["context"]
                if chunk.get("done"):
                    break
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Impossible de joindre Ollama sur http://localhost:11434. "
            f"Verifie que `ollama serve` est lance et que le modele `{model}` est disponible."
        ) from exc

    return "".join(parts).strip(), next_context


def normalize_word_response(response: str) -> str:
    cleaned = " ".join(response.strip().split())
    if not cleaned:
        return "jsp mdr"
    if cleaned.lower() in {"impossible", "aucun", "introuvable"}:
        return "jsp mdr"
    return cleaned


def simplify_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def extract_single_word(response: str) -> Optional[str]:
    candidate = response.strip()
    candidate = candidate.strip(".,;:!?()[]{}\"")
    if not candidate or " " in candidate:
        return None
    if not re.fullmatch(r"[A-Za-zÀ-ÿ'-]+", candidate):
        return None
    return candidate


def is_valid_word_for_sequence(word: str, sequence: str) -> bool:
    return is_valid_word_for_sequence_with_rules(word, sequence, False, False)


def is_valid_word_for_sequence_with_rules(
    word: str,
    sequence: str,
    require_long_word: bool,
    require_compound_word: bool,
) -> bool:
    lowered = simplify_text(word)
    simplified_sequence = simplify_text(sequence)
    if not simplified_sequence:
        return False
    if "'" in word:
        return False
    if require_compound_word:
        if "-" not in word:
            return False
        parts = word.split("-")
        if len(parts) < 2 or any(not part for part in parts):
            return False
        if any(not re.fullmatch(r"[A-Za-zÀ-ÿ]+", part) for part in parts):
            return False
    elif "-" in word:
        return False
    if len(lowered) < max(3, len(simplified_sequence)):
        return False
    if require_long_word and len(lowered.replace("-", "")) < 20:
        return False
    if len(set(lowered)) <= 2 and len(lowered) >= 5:
        return False
    if any(pattern in lowered for pattern in SUSPICIOUS_PATTERNS):
        return False
    if lowered in ARTICLES:
        return False
    if any(lowered.startswith(prefix) for prefix in ARTICLE_PREFIXES):
        return False
    return simplified_sequence in lowered


def initialize_context(model: str, setup_prompt: str, options: Optional[dict] = None) -> List[int]:
    _, context = ollama_generate(f"{setup_prompt} Reponds seulement: OK.", model=model, options=options)
    return context


def normalize_language(language: str) -> str:
    value = (language or DEFAULT_LANGUAGE).strip().lower()
    return value if value in LANGUAGE_RULES else DEFAULT_LANGUAGE


def generate_word_for_sequence(
    sequence: str,
    model: str,
    generation_context: List[int],
    lexical_theme: str = DEFAULT_LEXICAL_THEME,
    language: str = DEFAULT_LANGUAGE,
    prefer_long_words: bool = False,
    require_compound_words: bool = False,
    max_attempts: int = MAX_ATTEMPTS,
    excluded_words: Optional[List[str]] = None,
    logger: Optional[Callable[[Dict[str, Any]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Tuple[str, List[int]]:
    cleaned_sequence = sequence.strip()
    if not cleaned_sequence:
        return "jsp mdr", generation_context

    banned = [word for word in (excluded_words or []) if word and word != "jsp mdr"]
    banned_text = ""
    if banned:
        banned_text = " N'utilise surtout aucun de ces mots deja tentes: " + ", ".join(sorted(set(banned))) + "."
    language_key = normalize_language(language)
    language_rules = LANGUAGE_RULES[language_key]
    cleaned_theme = lexical_theme.strip() if lexical_theme else DEFAULT_LEXICAL_THEME
    theme_text = ""
    if (
        not prefer_long_words
        and not require_compound_words
        and cleaned_theme
        and cleaned_theme.lower() != DEFAULT_LEXICAL_THEME
    ):
        theme_text = language_rules["theme"].format(theme=cleaned_theme)
    long_word_text = ""
    if prefer_long_words:
        if language_key == "fr":
            long_word_text = (
                " Priorite absolue: reponds uniquement avec un mot francais monstrueusement long, d'au moins 20 lettres "
                "(hors tirets), de preference une construction savante, erudite, technique ou une fusion de concepts "
                "du style hippopotomonstrosesquipedaliophobie. "
                "Refuse totalement les mots courts, banals ou de moins de 20 lettres."
            )
        elif language_key == "en":
            long_word_text = (
                " Absolute priority: reply only with an extremely long real English word of at least 20 letters "
                "(excluding hyphens), ideally scholarly, technical, extravagant, or a concept-fusion style word "
                "similar in spirit to hippopotomonstrosesquipedaliophobia. "
                "Reject any short, plain, or sub-20-letter answer."
            )
        elif language_key == "es":
            long_word_text = (
                " Prioridad absoluta: responde solo con una palabra espanola extremadamente larga, de al menos 20 letras "
                "(sin contar guiones), idealmente culta, tecnica, erudita o una fusion de conceptos "
                "del estilo hippopotomonstrosesquipedaliophobia. "
                "Rechaza por completo cualquier palabra corta o de menos de 20 letras."
            )
        else:
            long_word_text = (
                " Prioritas absoluta: responde tantum cum verbo Latino prorsus longo, saltem 20 litterarum "
                "(lineolis non numeratis), potius erudito, technico, aut quasi ex coniunctione notionum formato "
                "more hippopotomonstrosesquipedaliophobiae. "
                "Omnia verba breviora vel vulgaria reiice."
            )
    compound_word_text = ""
    if require_compound_words:
        if language_key == "fr":
            compound_word_text = (
                " Priorite absolue: reponds uniquement avec un mot compose contenant obligatoirement au moins un tiret "
                "entre chaque element, par exemple nom-nom ou adjectif-nom. "
                "N'ecris jamais un mot simple sans tiret. Si tu ne trouves pas de vrai mot compose valide, reponds impossible."
            )
        elif language_key == "en":
            compound_word_text = (
                " Absolute priority: reply only with a hyphenated compound word containing at least one hyphen between parts, "
                "for example noun-noun or adjective-noun. "
                "Never output a single unhyphenated word. If no valid hyphenated compound exists, reply impossible."
            )
        elif language_key == "es":
            compound_word_text = (
                " Prioridad absoluta: responde solo con una palabra compuesta con al menos un guion entre sus partes. "
                "Nunca escribas una palabra simple sin guion. Si no existe una compuesta valida, responde impossible."
            )
        else:
            compound_word_text = (
                " Prioritas absoluta: responde tantum cum verbo composito lineola inter partes posita. "
                "Numquam da verbum simplex sine lineola. Si nullum tale verbum validum invenitur, responde impossible."
            )

    last_response = "jsp mdr"
    attempt_budget = max(1, int(max_attempts or MAX_ATTEMPTS))
    for attempt in range(attempt_budget):
        if should_stop is not None and should_stop():
            if logger is not None:
                logger({"event": "cancelled"})
            return "jsp mdr", generation_context

        started_at = time.perf_counter()
        nonce = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        flavor = random.choice(ATTEMPT_FLAVORS)
        prompt = (
            f"{language_rules['base'].format(sequence=cleaned_sequence)} "
            f"{theme_text}{long_word_text}{compound_word_text}{banned_text} "
            f"{flavor} Identifiant de tentative: {nonce}."
        )
        if attempt > 0:
            prompt += f" {language_rules['retry']}"

        response, _ = ollama_generate(prompt, model=model, context=generation_context, options=GENERATOR_OPTIONS)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        normalized = normalize_word_response(response)
        if logger is not None:
            logger({
                "event": "attempt",
                "attempt": attempt + 1,
                "max_attempts": MAX_ATTEMPTS,
                "sequence": cleaned_sequence,
                "raw": response,
                "normalized": normalized,
                "theme": cleaned_theme,
                "nonce": nonce,
                "language": language_key,
            })
        if normalized == "jsp mdr":
            last_response = normalized
            continue

        word = extract_single_word(normalized)
        if not word:
            if logger is not None:
                logger({
                    "event": "reject",
                    "attempt": attempt + 1,
                    "word": normalized,
                    "reason": "format",
                })
            last_response = normalized
            continue

        if not is_valid_word_for_sequence_with_rules(
            word,
            cleaned_sequence,
            require_long_word=prefer_long_words,
            require_compound_word=require_compound_words,
        ):
            if logger is not None:
                logger({
                    "event": "reject",
                    "attempt": attempt + 1,
                    "word": word,
                    "reason": "sequence_or_form",
                })
            last_response = word
            continue

        if logger is not None:
            logger({
                "event": "candidate",
                "attempt": attempt + 1,
                "word": word,
            })

        if logger is not None:
            logger({"event": "accepted", "attempt": attempt + 1, "word": word})
        return word.lower(), generation_context

    if logger is not None:
        logger({"event": "failed", "word": last_response})
    return "jsp mdr", generation_context


def build_base_context(model: str) -> List[int]:
    return initialize_context(model, LANGUAGE_RULES[DEFAULT_LANGUAGE]["setup"], GENERATOR_OPTIONS)


def build_base_context_for_language(model: str, language: str) -> List[int]:
    language_key = normalize_language(language)
    return initialize_context(model, LANGUAGE_RULES[language_key]["setup"], GENERATOR_OPTIONS)


def get_ollama_status(model: str) -> Tuple[bool, str]:
    if shutil.which("ollama") is None:
        return False, "La commande `ollama` est introuvable. Installe Ollama."

    try:
        result = subprocess.run(
            ["ollama", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return False, f"Impossible d'executer `ollama list`: {exc}"

    if result.returncode != 0:
        stderr = result.stderr.strip() or "erreur inconnue"
        return False, f"`ollama list` a echoue: {stderr}"

    output = result.stdout
    if model not in output:
        return False, f"Le modele `{model}` n'est pas installe. Lance `ollama pull {model}`."

    return True, f"Ollama est disponible et le modele `{model}` est installe."


if __name__ == "__main__":
    try:
        generation_context = build_base_context(DEFAULT_MODEL)
        print("Entrez une suite de lettres. Tapez q pour quitter.")

        while True:
            try:
                sequence = input("> ").strip()
            except EOFError:
                print()
                break

            if sequence.lower() in {"q", "quit", "exit"}:
                break

            if not sequence:
                continue

            word, _ = generate_word_for_sequence(
                sequence,
                DEFAULT_MODEL,
                generation_context,
            )
            print(word)
    except KeyboardInterrupt:
        print()
    except Exception as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        sys.exit(1)
