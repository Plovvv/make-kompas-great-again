"""Мод «Метизы и фитинги»: каталог стандартных крепёжных деталей, создание детали с нужным именем."""

from pathlib import Path


def run(ctx):
    from mkga.manifest import load_manifest
    from mkga_fasteners.catalog import load_catalog
    from mkga_fasteners.ui import run_app

    mod_dir = Path(ctx.mod_dir)
    builtin = mod_dir / "data"
    user_dir = Path(ctx.data_dir) / "standards"          # свои детали пользователя (остаются локально)
    catalog = load_catalog(builtin, user_dir)
    run_app(ctx, catalog, version=load_manifest(mod_dir).version, user_dir=user_dir, builtin_dir=builtin)
