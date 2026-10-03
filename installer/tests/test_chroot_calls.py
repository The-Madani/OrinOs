"""Check that no arch_chroot call relies on a shell.

Run with:  python3 installer/tests/test_chroot_calls.py

archinstall's arch_chroot() passes its argument through shlex.split() and
os.execve(), so `>`, `&&`, `||`, `|` and `;` arrive as ordinary arguments to
the program. A command like

    printf "%s\\n" "LANG=fa_IR.UTF-8" > /etc/locale.conf

becomes ['printf', '%s\\n', 'LANG=fa_IR.UTF-8', '>', '/etc/locale.conf']:
the file is never created, the exit status is 0, and nothing is logged. That
silence is what made several installation steps do nothing at all.

So every arch_chroot call is inspected: shell operators are only allowed
when the command explicitly starts a shell (`bash -c`, `su -c`).
"""
import ast  # noqa: E402
import sys  # noqa: E402
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / 'install.py'
failures = []

# Operators that a non-shell execve() would pass through as arguments.
OPERATORS = ('&&', '||', '|', ';', '>', '<', '>>', '$(', '`')
# Calling a shell explicitly is the supported way to use any of them.
SHELL_PREFIXES = ('bash -c', 'sh -c', 'su -')


def check(label, condition, detail=''):
    print(f'{"PASS" if condition else "FAIL"}  {label}'
          + (f'   {detail}' if detail and not condition else ''))
    if not condition:
        failures.append(label)


tree = ast.parse(BACKEND.read_text())

# Every arch_chroot("...") call in the file.
calls = []
for node in ast.walk(tree):
    if (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'arch_chroot'
            and node.args):
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            calls.append((argument.value, node.lineno))
        elif isinstance(argument, ast.JoinedStr):
            # An f-string: reconstruct roughly so operators are still visible.
            text = ''.join(p.value for p in argument.values
                           if isinstance(p, ast.Constant)
                           and isinstance(p.value, str))
            calls.append((text, node.lineno))

check('the backend calls arch_chroot at all', calls,
      'no arch_chroot call found — has the backend been rewritten?')

bad = []
for command, lineno in calls:
    if any(op in command for op in SHELL_PREFIXES):
        continue
    found = [op for op in OPERATORS if op in command]
    if found:
        bad.append(f'line {lineno}: {found} in {command[:60]!r}')

check('no arch_chroot call depends on a shell', not bad,
      'these would silently do nothing: ' + '; '.join(bad))

# --- the specific steps that were broken -------------------------------------
source = BACKEND.read_text()
for label, needle in [
        ('the locale is generated', 'locale.gen'),
        ('the volume label is set from the host, not a chroot shell',
         "run(['e2label', root_dev"),
        ('the root password is set through stdin',
         "['arch-chroot', '-S', str(target), 'chpasswd']"),
        ('the orinos repository is copied to the same path pacman.conf uses',
         'src.relative_to'),
        ('the target gets the [orinos] repository in its pacman.conf',
         'on_target=True'),
        ('interrupted runs are cleaned up too',
         'except BaseException'),
        ('the user unit directory is created',
         'default.target.wants'),
]:
    check(f'{label}', needle in source, f'not found: {needle!r}')

print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL ARCH_CHROOT CHECKS PASS')