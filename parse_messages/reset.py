#!/usr/bin/env python3
import shlex
import subprocess
import sys


def build_commands(n: int):
    prev_n = n - 1
    cmds = [
        f"mv parsed_{n}.json loadable",
        f"mv {n} {n}.done",
        f"cp parse_{n}.py parse_{prev_n}.py",
        f"mv parse_{n}.py code",
    ]
    return cmds


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
        # Split into argv safely
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

    try:
        n = int(sys.argv[1])
    except ValueError:
        print("Error: <number> must be an integer (e.g., 1806).", file=sys.stderr)
        sys.exit(2)

    cmds = build_commands(n)

    # Print and confirm
    if not prompt_approve(cmds):
        print("Aborted.")
        sys.exit(0)

    # Execute
    run_commands(cmds)
    print("Done.")


if __name__ == "__main__":
    main()
