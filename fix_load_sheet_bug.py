from pathlib import Path

p = Path("bot.py")
text = p.read_text()

old = '''async def find_row(name):
    df = await load_sheet(day)'''

new = '''async def find_row(name):
    df = await load_sheet(now_local().day)'''

text = text.replace(old, new)

p.write_text(text)

print("find_row() исправлен")
