# GALACTIC CONCLAVE v0.6.0
## The "Stochastic Railgun" Release

Look, we built something that lets you actually *talk* to the AIs in your Stellaris save, and they'll change their minds, declare war, or offer trade deals based on what you say. The diplomacy screen in vanilla is basically a cardboard cutout. This is not that.

(Fair warning: if you can't read, this won't help you. The analphabetic marsupials who tried to run the beta have all been composted and resold to the Galactic Market as fertilizer.)

## Installation (The Boring Part)

1. Download `GalacticConclave.exe` from releases
2. Run it while Stellaris is sitting there unpaused
3. Point it at your save folder (`Documents/Paradox Interactive/Stellaris/save games`)
4. Configure your LLM:
   - **Local mode**: Put `ollama` in as your API key and spin up a model like `llama3.2`
   - **Cloud mode**: Paste in your key from OpenAI, DeepSeek, Anthropic, whoever. Pay to play
5. Tell it your console key (default's the backtick key). Stellaris has this in Settings → Controls. Get it wrong and you're just waving at the void
6. Hit go. It'll find your newest save and list every empire

## The Actual Architecture

The Brain (`main.py`) orchestrates everything. The Face (`ui.py`) keeps the interface lean—no bloat, just what you need. The Bridge (`llm_client.py`) pumps your messages through whatever LLM you picked. The Hands (`game_io.py`) is the real magic: instead of clicking buttons like a Victorian telegraph operator, v0.6 writes commands to `conclave_cmd.txt` in your root folder and fires them off with the `run` command. One signal, one outcome.

The Eyes (`save_parser.py`) parse your save file. Line 217 is sacred. Mess with it and reality folds in on itself.

The Soul (`prompts.py`) keeps the AI from just... talking like a chatbot. Each empire gets tuned to their actual government type and ethos. A Fanatical Purifier won't pretend to like you. 

The Compass (`config.py`) hides your secrets in `%APPDATA%` like they're supposed to be.

## What This Actually Does

Every empire has a personality pulled straight from your save file. A militarist will bristle at insults. A pacifist will flinch at threats. They respond to what you actually say, not just predetermined dialog wheels.

Broadcast a message to everyone at once. Watch the chaos unfold.

When an empire proposes something consequential—a trade agreement, a war declaration, an alliance—an APPLY button materializes. Hit it and the console command gets executed. The diplomacy becomes *real*.

Mock mode lets you test the whole interface without an API key. Responses are stubbed, but you can see how everything flows.

The app refreshes every 30 seconds, so autosaves get picked up mid-session. Jump back in and resume without starting over.

Ironman mode gets detected automatically. Console injection disables itself so your achievements stay clean. The roleplay still works; the save file remains untouched.

## Requirements

Windows 10 or 11. Stellaris. Python 3.10+ if you're building from source. Ollama if you want local models (grab it from ollama.com).

## If Something Breaks

Console commands not executing? Check that you launched Stellaris with `-open_console` in the Steam launch options. Verify your console key matches what Stellaris thinks it is. Make sure Stellaris is actually the active window when you hit APPLY. Ironman saves can't use console commands—it's a hard lock from Paradox.

Missing modules when running from source? Try `rebuild_clean_oncemore.bat`.

AI isn't responding? Enable Mock Mode to check if the UI works at all. Verify your API key. Check your internet if you're using a cloud provider.

## Source Code

```bash
git clone https://github.com/your-repo/GalacticConclave.git
cd GalacticConclave
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

This escapes the default Stellaris experience and actually gives you consequences for your diplomatic choices. That's the whole point.
