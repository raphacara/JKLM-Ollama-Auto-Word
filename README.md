# JKLM Ollama Auto

Tampermonkey userscript + local Python server to play BombParty on `jklm.fun` with Ollama.

## Features

- reads the current syllable from JKLM
- asks a local Ollama-backed server for a valid word
- types and submits the word with configurable human-like timing
- floating in-game UI for settings and status
- `Longs` and `Composes` special modes for big LLMs
- fallback from special modes back to normal generation
- optional auto re-join mode based on the `Rejoindre la partie` button

## Project Files

- `jklm_tampermonkey.user.js`: browser userscript
- `jklm_local_server.py`: local HTTP server on `127.0.0.1:8765`
- `ollama_random_word.py`: Ollama prompts, generation, filtering, validation
- `launch_jklm_server.command`: simple launcher for macOS
- `jklm_settings.json`: local config

## Requirements

- Python 3
- Ollama installed
- at least one Ollama model installed
- Tampermonkey installed in your browser

## Quick Start

### 1. Install or verify Ollama

List installed models:

```bash
ollama list
```

Pull a model if needed:

```bash
ollama pull gemma3:12b
```

Start Ollama if necessary:

```bash
ollama serve
```

### 2. Create your local settings file

Example:

```json
{
  "lexical_theme": "libre",
  "model": "gemma3:12b", 
  "language": "fr",
  "human_mode": "humain rapide",
  "long_words": false,
  "compound_words": false
}
```

note : light models like gemma3:1b works well too. but you know, he bigger, the better ;)

### 3. Start the local server

```bash
./launch_jklm_server.command
```

Or directly:

```bash
python3 jklm_local_server.py
```

### 4. Install the userscript

In Tampermonkey:

1. create a new script
2. replace its content with `jklm_tampermonkey.user.js`
3. save it
4. make sure it is enabled

### 5. Open a JKLM room

Open a real room URL on `jklm.fun`, not just the homepage.

## How It Works

### Browser side

The userscript:

- finds the active syllable
- finds your input field
- queries the local server
- receives a candidate word
- types it
- submits it
- retries when the submission is rejected

### Server side

The local server:

- reads `jklm_settings.json`
- reloads settings automatically
- prepares Ollama context per model/language
- generates several candidates
- validates them
- returns one clean word to the userscript

## UI Overview

The in-game panel includes:

- server status: `ONLINE` / `OFFLINE`
- automation toggle: `ON` / `OFF`
- auto re-join toggle: circular arrow button
- collapsible info section
- settings section

### Settings

Standard settings:

- language
- human mode
- model
- theme

Special block:

- `Longs`: prefer very long words
- `Composes`: require hyphenated words

## Generation Logic

The global generation budget is `30` attempts.

When `Longs` or `Composes` is enabled:

- the server first tries `5` special-mode attempts
- if nothing valid is found, it automatically falls back to normal generation

## Human Modes

Available modes:

- `godlike`
- `humain rapide`
- `humain normal`
- `humain lent`

These affect:

- typing speed
- think time
- submit timing
- pauses
- occasional typo simulation

## Auto Re-Join

When enabled:

- the script scans for the visible button `Rejoindre la partie`
- it scans every `5` seconds
- when found, it clicks once
- after clicking, it waits `30` seconds before scanning again

When disabled:

- nothing happens

## Local API

### `GET /health`

```bash
curl http://127.0.0.1:8765/health
```

### `GET /settings`

```bash
curl http://127.0.0.1:8765/settings
```

### `POST /settings`

```bash
curl -X POST http://127.0.0.1:8765/settings \
  -H 'Content-Type: application/json' \
  -d '{"language":"fr","human_mode":"humain rapide"}'
```

### `POST /word`

```bash
curl -X POST http://127.0.0.1:8765/word \
  -H 'Content-Type: application/json' \
  -d '{"sequence":"tion","exclude":[],"request_id":"test-1"}'
```

With temporary overrides:

```bash
curl -X POST http://127.0.0.1:8765/word \
  -H 'Content-Type: application/json' \
  -d '{"sequence":"anti","exclude":[],"request_id":"test-2","overrides":{"long_words":true,"max_attempts":5}}'
```

### `POST /cancel`

```bash
curl -X POST http://127.0.0.1:8765/cancel \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"test-1"}'
```

### `POST /shutdown`

```bash
curl -X POST http://127.0.0.1:8765/shutdown
```

## Useful Commands

Check the server:

```bash
curl http://127.0.0.1:8765/health
```

Check the listening port:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

Compile Python files:

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile jklm_local_server.py ollama_random_word.py
```

## Troubleshooting

### The UI does not appear

- make sure the userscript is enabled
- make sure you are inside a real JKLM room
- reload the page

### The UI shows `OFFLINE`

- start `jklm_local_server.py`
- verify `curl http://127.0.0.1:8765/health`

### The server does not start

Check Ollama:

```bash
ollama list
```

If the port is already used:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

### No word is found

- test `/word` manually
- try a simpler theme
- try another model
- disable `Longs` and `Composes`

### Re-join does not click

The current implementation relies on the visible button text `Rejoindre la partie`.

If JKLM changes that UI text or DOM structure, update `findJoinGameButton()` in `jklm_tampermonkey.user.js`.

# HAVE FUN WITH THIS VIRTUAL INTELLIGENCE THAT BEHAVES LIKE A HUMAN, AND WAY FUNNIER THAN A BASIC BOT. 
# FEEL FREE TO TRY DIFFERENT OPEN SOURCE MODELS
