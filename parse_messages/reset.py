#!/usr/bin/env python3
import shlex
import subprocess
import sys


def build_commands(n_str: str):
    prev_n = str(int(n_str) - 1).zfill(len(n_str))  # keep same width as input
    return [
        f"mv parsed_{n_str}.json loadable",
        f"mv {n_str} {n_str}.done",
        f"cp parse_{n_str}.py parse_{prev_n}.py",
        f"mv parse_{n_str}.py code",
    ]


def prompt_approve(cmds):
    print("The following commands will be executed:")
    for c in cmds:
        print(f"  {c}")
    while True:
        ans = input("Proceed? [y/n]: ").strip().lower()
        if ans in ("y", "n"):
            return ans == "y"
        print("Please enter 'y' or 'n'.")


def run_commands(cmds):
    for c in cmds:
        print(f"+ {c}")
        argv = shlex.split(c)
        try:
            subprocess.run(argv, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Command failed with exit code {e.returncode}: {c}")
            sys.exit(e.returncode)
        except FileNotFoundError:
            print(f"Command not found: {argv[0]}")
            sys.exit(127)


def main():
    if len(sys.argv) != 2:
        print("Usage: python manage_batch.py <number>", file=sys.stderr)
        sys.exit(1)

    n_str = sys.argv[1].strip()
    if not n_str.isdigit():
        print(
            "Error: <number> must be all digits (e.g., 0912 or 1806).", file=sys.stderr
        )
        sys.exit(2)

    cmds = build_commands(n_str)

    if not prompt_approve(cmds):
        print("Aborted.")
        sys.exit(0)

    run_commands(cmds)
    print("Done.")


if __name__ == "__main__":
    main()
