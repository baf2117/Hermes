---
description: Actualiza este fork desde upstream (solo avance limpio, sin push)
allowed-tools: Bash(git remote:*), Bash(git status:*), Bash(git fetch upstream:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git log:*), Bash(git merge --ff-only:*)
---
Actualiza este fork desde el remoto upstream. Solo aplica si el proyecto es un fork.
1. Comprueba que existe el remoto upstream (git remote -v) y que el árbol está limpio
   (git status). Si no existe el remoto, dime que este proyecto no parece un fork y para.
   Si el árbol no está limpio, para y dime qué hacer.
2. Ejecuta git fetch upstream y dime en qué rama estoy y cuántos commits tengo por delante
   y por detrás de upstream (git rev-list --left-right --count HEAD...upstream/<rama>).
3. Si no tengo commits propios, haz git merge --ff-only upstream/<rama>.
4. Si tengo commits propios (divergencia), NO hagas merge ni rebase: muéstrame el
   resumen (git log --oneline HEAD..upstream/<rama>) y pregúntame qué prefiero.
5. Nunca uses reset, force ni git push. Al terminar, dame el comando de push para que lo
   ejecute yo.
