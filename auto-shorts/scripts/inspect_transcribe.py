from pathlib import Path
path = Path('auto_shorts/transcribe.py')
text = path.read_text(encoding='utf-8')
lines = text.splitlines()
print('exists', path.exists())
print('count', len(lines))
for i in range(130, 150):
    print(f'{i+1}: {lines[i]}')
