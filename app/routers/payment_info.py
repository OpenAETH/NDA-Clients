from fastapi import APIRouter, Query

from app.core import store

router = APIRouter()


@router.get("")
async def get_payment_info(lang: str = Query(store.DEFAULT_LANG, description="UI language: en | es")):
    """
    Datos de pago (transferencias ARS/USD/EUR/cripto) leídos desde
    data/payment_info.json. Editable a mano sin tocar el código.
    Solo se devuelven los métodos habilitados, localizados a `lang`.
    """
    data = store.load_document("payment_info")
    methods = [m for m in data.get("methods", []) if m.get("enabled", True)]
    return {"methods": store.localize(methods, lang)}
