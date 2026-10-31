"""Evidence script: what encoding does a plain open() get on this machine?"""
import locale
import sys

print('python', sys.version.split()[0], 'utf8_mode', sys.flags.utf8_mode)
print('preferred encoding:', locale.getpreferredencoding(False))
raw = open(r'backend\requirements.txt', 'rb').read()
print('file bytes head:', raw[:24])
try:
    text = open(r'backend\requirements.txt').read()
    print('locale read: OK,', len(text), 'chars')
except UnicodeDecodeError as error:
    print('locale read: FAILED ->', error)
