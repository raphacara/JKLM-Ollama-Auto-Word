#!/bin/zsh
DESKTOP_APP="$HOME/Desktop/JKLM bot.app"

if [ -d "$DESKTOP_APP" ]; then
  open "$DESKTOP_APP"
else
  echo "JKLM bot.app est introuvable sur le Bureau."
  echo "App attendue: $DESKTOP_APP"
  read "unused?Appuie sur Entree pour fermer."
fi
