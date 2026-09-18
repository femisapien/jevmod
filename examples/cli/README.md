# CLI

`jevmod check` reads one message per line from stdin and exits 0 when nothing triggers, 1 when something does,
2 on an error. That makes it a building block for shell scripts and CI.

```bash
jevmod init                                            # TypeSafe key
bash examples/cli/screen_file.sh comments.txt          # prints hits, exits 1 if there are any
bash examples/cli/screen_file.sh comments.txt --rule "No politics. Game news is fine."
```

`screen_file.sh` prints only the lines that triggered and passes extra flags through to `jevmod check`.

`pre-commit.sh` screens the staged `.md` and `.txt` files and blocks the commit on a hit. Install it with:

```bash
cp examples/cli/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

Both need `jevmod` on PATH and `python` for the JSON filtering (no jq dependency).
