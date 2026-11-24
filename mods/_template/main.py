"""Шаблон мода MKGA.

Хаб вызывает run(ctx). Что есть в ctx:
  ctx.kompas()  подключение к КОМПАСу (API5 + API7), создаётся при первом вызове
  ctx.log(text) вывод сообщения
  ctx.mod_dir   папка мода
  ctx.data_dir  папка для данных мода (настройки, кэш)
"""


def run(ctx):
    k = ctx.kompas()
    doc = k.active_document
    if doc is None:
        ctx.log("Нет открытого документа")
        return
    # Только чтение. Сообщения идут в журнал мода, а не в окно КОМПАСа:
    # блокирующее окно (k.message) подвесило бы и мод, и КОМПАС.
    ctx.log(f"Активный документ: {doc.Name}")
