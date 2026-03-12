import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from ollama_random_word import (
    DEFAULT_LEXICAL_THEME,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    MAX_ATTEMPTS,
    build_base_context_for_language,
    generate_word_for_sequence,
    get_ollama_status,
)


HOST = "127.0.0.1"
PORT = 8765
SETTINGS_PATH = Path(__file__).with_name("jklm_settings.json")
LEXICAL_THEME_OPTIONS = [
    "libre",
    "animaux",
    "monstres",
    "fantasy",
    "science-fiction",
    "mythologie",
    "amour",
    "seduction",
    "jalousie",
    "mort",
    "horreur",
    "violence",
    "crime",
    "guerre",
    "nourriture",
    "alcool",
    "drogue",
    "medecine",
    "science",
    "espace",
    "technologie",
    "internet",
    "argent",
    "luxe",
    "religion",
    "politique",
    "musique",
    "cinema",
    "sport",
    "nature",
    "ocean",
    "feu",
    "sexe",
    "dragueur",
]
LANGUAGE_OPTIONS = ["fr", "en", "es", "la"]
HUMAN_MODE_OPTIONS = ["godlike", "humain rapide", "humain normal", "humain lent"]


def normalize_human_mode(value: str) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "discret": "humain rapide",
        "normal": "humain normal",
        "humain normal": "humain normal",
        "humain rapide": "humain rapide",
        "humain lent": "humain lent",
        "godlike": "godlike",
    }
    if normalized == "instantane":
        return "godlike"
    return aliases.get(normalized, "humain normal")


class Ansi:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def colorize(text: str, color: str) -> str:
    return f"{color}{text}{Ansi.RESET}"


def print_header(title: str) -> None:
    line = "=" * 72
    print(colorize(line, Ansi.DIM))
    print(colorize(f"  {title}", Ansi.BOLD + Ansi.CYAN))
    print(colorize(line, Ansi.DIM))


def is_server_already_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=1.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        return False


def shorten(text: str, limit: int = 28) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.cached_mtime = None
        self.cached_settings = {
            "lexical_theme": DEFAULT_LEXICAL_THEME,
            "model": DEFAULT_MODEL,
            "language": DEFAULT_LANGUAGE,
            "human_mode": "humain normal",
            "long_words": False,
            "compound_words": False,
        }

    def load(self) -> Dict[str, str]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return self.cached_settings

        if self.cached_mtime == stat.st_mtime:
            return self.cached_settings

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self.cached_settings

        lexical_theme = str(payload.get("lexical_theme", DEFAULT_LEXICAL_THEME)).strip() or DEFAULT_LEXICAL_THEME
        model = str(payload.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        language = str(payload.get("language", DEFAULT_LANGUAGE)).strip().lower() or DEFAULT_LANGUAGE
        human_mode = normalize_human_mode(payload.get("human_mode", "humain normal"))
        long_words = bool(payload.get("long_words", False))
        compound_words = bool(payload.get("compound_words", False))
        self.cached_settings = {
            "lexical_theme": lexical_theme,
            "model": model,
            "language": language,
            "human_mode": human_mode,
            "long_words": long_words,
            "compound_words": compound_words,
        }
        self.cached_mtime = stat.st_mtime
        print(colorize(f"[CONF] theme lexical charge: {lexical_theme}", Ansi.MAGENTA))
        print(colorize(f"[CONF] modele charge: {model}", Ansi.MAGENTA))
        print(colorize(f"[CONF] langue chargee: {language}", Ansi.MAGENTA))
        print(colorize(f"[CONF] mode humain charge: {human_mode}", Ansi.MAGENTA))
        print(colorize(f"[CONF] mots longs: {'on' if long_words else 'off'}", Ansi.MAGENTA))
        print(colorize(f"[CONF] mots composes: {'on' if compound_words else 'off'}", Ansi.MAGENTA))
        return self.cached_settings

    def save(self, settings: Dict[str, str]) -> Dict[str, str]:
        lexical_theme = str(settings.get("lexical_theme", DEFAULT_LEXICAL_THEME)).strip() or DEFAULT_LEXICAL_THEME
        model = str(settings.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        language = str(settings.get("language", DEFAULT_LANGUAGE)).strip().lower() or DEFAULT_LANGUAGE
        human_mode = normalize_human_mode(settings.get("human_mode", "humain normal"))
        long_words = bool(settings.get("long_words", False))
        compound_words = bool(settings.get("compound_words", False))
        if language not in LANGUAGE_OPTIONS:
            language = DEFAULT_LANGUAGE
        if human_mode not in HUMAN_MODE_OPTIONS:
            human_mode = "humain normal"

        payload = {
            "lexical_theme": lexical_theme,
            "model": model,
            "language": language,
            "human_mode": human_mode,
            "long_words": long_words,
            "compound_words": compound_words,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        self.cached_settings = payload
        self.cached_mtime = self.path.stat().st_mtime
        print(colorize(f"[CONF] reglages sauvegardes: {payload}", Ansi.MAGENTA))
        return payload


class WordService:
    def __init__(self) -> None:
        self.settings_store = SettingsStore(SETTINGS_PATH)
        self.model = DEFAULT_MODEL
        self.language = DEFAULT_LANGUAGE
        self.cancel_flags: Dict[str, threading.Event] = {}
        print_header("JKLM Ollama Server")
        print(colorize(f"[BOOT] config: {SETTINGS_PATH.name}", Ansi.CYAN))
        settings = self.settings_store.load()
        self.model = settings["model"]
        self.language = settings["language"]
        print(colorize(f"[BOOT] modele: {self.model}", Ansi.CYAN))
        ok, status_message = get_ollama_status(self.model)
        if ok:
            print(colorize(f"[OK  ] {status_message}", Ansi.GREEN))
        else:
            print(colorize(f"[ERR ] {status_message}", Ansi.RED))
            print(colorize("[TIP ] demarre Ollama puis relance ce serveur.", Ansi.YELLOW))
            raise RuntimeError(status_message)
        print(colorize("[BOOT] creation des contextes Ollama...", Ansi.YELLOW))
        self.generation_context = build_base_context_for_language(self.model, self.language)
        print(colorize("[OK  ] contexte pret", Ansi.GREEN))
        print(colorize(f"[READY] theme lexical actif: {settings['lexical_theme']}", Ansi.GREEN))
        print(colorize(f"[READY] langue active: {settings['language']}", Ansi.GREEN))

    def _reload_context_if_needed(self, desired_model: str, desired_language: str) -> None:
        if desired_model == self.model and desired_language == self.language:
            return

        print(colorize(
            f"[CONF] changement detecte: modele {self.model} -> {desired_model} | langue {self.language} -> {desired_language}",
            Ansi.YELLOW,
        ))
        ok, status_message = get_ollama_status(desired_model)
        if not ok:
            raise RuntimeError(status_message)

        self.generation_context = build_base_context_for_language(desired_model, desired_language)
        self.model = desired_model
        self.language = desired_language
        print(colorize("[OK  ] nouveau contexte pret", Ansi.GREEN))

    def get_word(
        self,
        sequence: str,
        excluded_words: List[str],
        request_id: str,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        settings = self.settings_store.load()
        lexical_theme = settings["lexical_theme"]
        desired_model = settings["model"]
        desired_language = settings["language"]
        merged_overrides = overrides or {}
        long_words = self._coerce_bool(merged_overrides.get("long_words"), settings.get("long_words", False))
        compound_words = self._coerce_bool(merged_overrides.get("compound_words"), settings.get("compound_words", False))
        max_attempts = self._coerce_int(merged_overrides.get("max_attempts"), MAX_ATTEMPTS)
        self._reload_context_if_needed(desired_model, desired_language)
        cancel_flag = threading.Event()
        self.cancel_flags[request_id] = cancel_flag
        generation_mode = "compose" if compound_words else "long" if long_words else "normal"
        print()
        print(colorize("-" * 72, Ansi.DIM))
        print(colorize(
            f"tour  syllabe={sequence}  langue={self.language}  theme={lexical_theme or 'libre'}  mode={generation_mode}  essais={max_attempts}  modele={self.model}",
            Ansi.BOLD + Ansi.BLUE,
        ))
        if excluded_words:
            print(colorize(f"exclus  {', '.join(excluded_words)}", Ansi.DIM))

        try:
            word, _ = generate_word_for_sequence(
                sequence,
                self.model,
                self.generation_context,
                lexical_theme=lexical_theme,
                language=self.language,
                prefer_long_words=long_words,
                require_compound_words=compound_words,
                max_attempts=max_attempts,
                excluded_words=excluded_words,
                logger=self._log_generation,
                should_stop=cancel_flag.is_set,
            )

            if word == "jsp mdr":
                print(colorize("echec  aucun mot fiable", Ansi.RED))
            else:
                print(colorize(f"ok     mot retenu: {word}", Ansi.GREEN))

            return {
                "sequence": sequence,
                "word": word,
                "excluded_words": excluded_words,
                "lexical_theme": lexical_theme,
                "model": self.model,
                "language": self.language,
                "long_words": long_words,
                "compound_words": compound_words,
                "max_attempts": max_attempts,
                "request_id": request_id,
            }
        finally:
            self.cancel_flags.pop(request_id, None)

    @staticmethod
    def _coerce_bool(value: Any, default: bool) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        if value in (None, ""):
            return default
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default

    def cancel_request(self, request_id: str) -> None:
        cancel_flag = self.cancel_flags.get(request_id)
        if cancel_flag is not None:
            cancel_flag.set()
            print(colorize(f"stop   annulation {request_id}", Ansi.YELLOW))

    def get_available_models(self) -> List[str]:
        if shutil.which("ollama") is None:
            return [self.model]
        try:
            result = subprocess.run(
                ["ollama", "list"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return [self.model]
        if result.returncode != 0:
            return [self.model]

        models: List[str] = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if parts:
                models.append(parts[0])
        if self.model not in models:
            models.insert(0, self.model)
        return models or [self.model]

    def log_client_event(self, event_name: str, payload: Dict[str, str]) -> None:
        sequence = payload.get("sequence", "")
        word = payload.get("word", "")
        detail = payload.get("detail", "")
        if event_name == "proposed":
            print(colorize(f"propo  {word}", Ansi.CYAN))
        elif event_name == "typing":
            print(colorize(f"frappe {word}", Ansi.YELLOW))
        elif event_name == "submitted":
            print(colorize(f"envoi  {word}", Ansi.GREEN))
        elif event_name == "accepted":
            print(colorize(f"valide {word}", Ansi.BOLD + Ansi.GREEN))
        elif event_name == "rejected":
            print(colorize(f"refus  {word}", Ansi.RED))
        elif event_name == "retry":
            print(colorize(f"retry  {detail}", Ansi.MAGENTA))
        elif event_name == "cancelled":
            print(colorize(f"stop   {detail or 'tour termine'}", Ansi.YELLOW))
        else:
            print(colorize(f"event  {event_name} {payload!r}", Ansi.DIM))

    @staticmethod
    def _log_generation(event: Dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "attempt":
            attempt = int(event.get("attempt", 0))
            max_attempts = int(event.get("max_attempts", 0))
            normalized = shorten(event.get("normalized", ""))
            print(colorize(f"{attempt:02d}/{max_attempts:02d}  test   {normalized}", Ansi.DIM))
            return

        if kind == "reject":
            attempt = int(event.get("attempt", 0))
            word = shorten(event.get("word", ""))
            reason = event.get("reason", "")
            print(colorize(f"{attempt:02d}     rejet  {word}  [{reason}]", Ansi.RED))
            return

        if kind == "candidate":
            attempt = int(event.get("attempt", 0))
            word = shorten(event.get("word", ""))
            print(colorize(f"{attempt:02d}     garde  {word}", Ansi.GREEN))
            return

        if kind == "accepted":
            word = shorten(event.get("word", ""))
            print(colorize(f"choisi  {word}", Ansi.GREEN))
            return

        if kind == "failed":
            word = shorten(event.get("word", ""))
            print(colorize(f"aucun   dernier essai: {word}", Ansi.RED))
            return

        if kind == "cancelled":
            print(colorize("stop   recherche annulee", Ansi.YELLOW))
            return


SERVICE = WordService()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "JKLMOllamaServer/1.0"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok", "model": SERVICE.model, "language": SERVICE.language})
            return

        if parsed.path == "/settings":
            settings = SERVICE.settings_store.load()
            self._send_json(200, {
                **settings,
                "max_generation_attempts": MAX_ATTEMPTS,
                "options": {
                    "models": SERVICE.get_available_models(),
                    "languages": LANGUAGE_OPTIONS,
                    "human_modes": HUMAN_MODE_OPTIONS,
                    "lexical_themes": sorted(set(LEXICAL_THEME_OPTIONS + [settings["lexical_theme"]])),
                },
            })
            return

        if parsed.path == "/server":
            self._send_json(200, {"status": "online"})
            return

        if parsed.path == "/word":
            params = parse_qs(parsed.query)
            sequence = params.get("sequence", [""])[0]
            excluded_words = params.get("exclude", [])
            request_id = params.get("request_id", [""])[0]
            overrides = {
                "long_words": params.get("long_words", [None])[0],
                "compound_words": params.get("compound_words", [None])[0],
                "max_attempts": params.get("max_attempts", [None])[0],
            }
            self._handle_word(sequence, excluded_words, request_id, overrides)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        if parsed.path == "/word":
            sequence = str(payload.get("sequence", "")).strip()
            excluded_words = payload.get("exclude", [])
            request_id = str(payload.get("request_id", "")).strip()
            overrides = payload.get("overrides", {})
            if not isinstance(excluded_words, list):
                excluded_words = []
            excluded_words = [str(word).strip() for word in excluded_words if str(word).strip()]
            if not isinstance(overrides, dict):
                overrides = {}
            self._handle_word(sequence, excluded_words, request_id, overrides)
            return

        if parsed.path == "/cancel":
            request_id = str(payload.get("request_id", "")).strip()
            if request_id:
                SERVICE.cancel_request(request_id)
            self._send_json(200, {"status": "ok"})
            return

        if parsed.path == "/shutdown":
            self._send_json(200, {"status": "stopping"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        if parsed.path == "/settings":
            current = SERVICE.settings_store.load()
            merged = {
                "lexical_theme": payload.get("lexical_theme", current["lexical_theme"]),
                "model": payload.get("model", current["model"]),
                "language": payload.get("language", current["language"]),
                "human_mode": payload.get("human_mode", current["human_mode"]),
                "long_words": payload.get("long_words", current.get("long_words", False)),
                "compound_words": payload.get("compound_words", current.get("compound_words", False)),
            }
            saved = SERVICE.settings_store.save(merged)
            self._send_json(200, saved)
            return

        if parsed.path == "/event":
            event_name = str(payload.get("event", "")).strip()
            detail_payload = {
                "sequence": str(payload.get("sequence", "")).strip(),
                "word": str(payload.get("word", "")).strip(),
                "detail": str(payload.get("detail", "")).strip(),
            }
            SERVICE.log_client_event(event_name, detail_payload)
            self._send_json(200, {"status": "ok"})
            return

        self._send_json(404, {"error": "not found"})

    def _handle_word(
        self,
        sequence: str,
        excluded_words: List[str],
        request_id: str,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not sequence:
            self._send_json(400, {"error": "missing sequence"})
            return
        if not request_id:
            self._send_json(400, {"error": "missing request_id"})
            return

        try:
            result = SERVICE.get_word(sequence, excluded_words, request_id, overrides)
        except Exception as exc:
            print(colorize(f"[ERR ] {exc}", Ansi.RED))
            self._send_json(500, {"error": str(exc)})
            return

        self._send_json(200, result)

    def _send_json(self, status: int, payload: Dict[str, str]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    try:
        server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    except OSError as exc:
        if is_server_already_running():
            print(colorize(f"[OK  ] serveur deja actif sur http://{HOST}:{PORT}", Ansi.GREEN))
            print(colorize("[TIP ] ferme l'ancienne instance si tu veux en relancer une autre.", Ansi.YELLOW))
            return
        print(colorize(f"[ERR ] impossible d'ouvrir le port {PORT}: {exc}", Ansi.RED))
        return

    print(colorize(f"[LIST] serveur pret sur http://{HOST}:{PORT}", Ansi.BOLD + Ansi.GREEN))
    print(colorize("[TIP ] modifie jklm_settings.json pour changer le champ lexical.", Ansi.MAGENTA))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(colorize("\n[STOP] arret du serveur.", Ansi.RED))
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
