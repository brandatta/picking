import streamlit as st
import pandas as pd
import mysql.connector

# ================== CONFIG ==================
st.set_page_config(page_title="Picking - Pedidos (SAP)", layout="wide")

# ================== ESTILOS ==================
st.markdown("""
<style>
.block-container { padding-top: 2.5rem !important; }

/* Evitar que se corte el título */
h1, h2, h3 {
  margin-top: 0.2rem !important;
  margin-bottom: 0.8rem !important;
  line-height: 1.2 !important;
  white-space: normal !important;
}

/* Tarjetas */
.card {
  border: 1px solid #e9e9e9; border-radius: 12px; padding: 12px 14px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.04); background: #fff; height: 100%;
}
.card h4 { margin: 0 0 6px 0; font-size: 1rem; }
.card small { color: #666; }
.card .stButton>button { width: 100%; border-radius: 8px; padding: 6px 10px; }

/* Botones Streamlit: colores según "type" */
.stButton>button[kind="primary"] {                 /* VERDE (activo) */
  background-color: #28a745 !important;
  color: #fff !important;
  border: 1px solid #28a745 !important;
}
.stButton>button[kind="primary"]:hover {
  background-color: #218838 !important;
  border-color: #218838 !important;
}

.stButton>button[kind="secondary"] {               /* BLANCO (inactivo) */
  background-color: #ffffff !important;
  color: #333 !important;
  border: 1px solid #d9d9d9 !important;
}
.stButton>button[kind="secondary"]:hover {
  background-color: #f5f5f5 !important;
  color: #000 !important;
  border-color: #cfcfcf !important;
}

/* Cabecera y filas */
.detail-head { font-weight: 600; opacity: 0.9; padding: 6px 0; border-bottom: 1px solid #f0f0f0; }
.detail-row { border-bottom: 1px dashed #ececec; padding: 8px 0; }

/* Barra inferior fija */
.confirm-bar {
  position: sticky; bottom: 0; background: #fafafa; border-top: 1px solid #eee;
  padding: 12px; border-radius: 10px; margin-top: 16px;
  z-index: 1;
}
</style>
""", unsafe_allow_html=True)

# ================== CONEXIÓN MYSQL ==================
def get_conn():
    return mysql.connector.connect(
        host=st.secrets["app_marco_new"]["host"],
        user=st.secrets["app_marco_new"]["user"],
        password=st.secrets["app_marco_new"]["password"],
        database=st.secrets["app_marco_new"]["database"],
        port=st.secrets["app_marco_new"].get("port", 3306),
    )

# ================== DATA ACCESS ==================
@st.cache_data(ttl=30)
def get_orders(buscar: str | None = None) -> pd.DataFrame:
    base = "SELECT DISTINCT NUMERO, CLIENTE FROM sap"
    where, params = [], []
    if buscar:
        where.append("(CAST(NUMERO AS CHAR) LIKE %s OR CLIENTE LIKE %s)")
        params.extend([f"%{buscar}%", f"%{buscar}%"])
    q = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY NUMERO DESC LIMIT 150"
    conn = get_conn()
    df = pd.read_sql(q, conn, params=params)
    conn.close()

    # Formatear CLIENTE: si es numérico y entero, mostrar sin .0
    df["CLIENTE"] = df["CLIENTE"].apply(
        lambda x: str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else str(x)
    )
    return df

def get_order_items(numero: int) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT NUMERO, CLIENTE, CODIGO, CANTIDAD, COALESCE(PICKING, 'N') AS PICKING
        FROM sap
        WHERE NUMERO = %s
        ORDER BY CODIGO
        """,
        conn, params=[numero]
    )
    conn.close()

    # Normalizar PICKING
    df["PICKING"] = (
        df["PICKING"]
        .fillna("N")
        .astype(str)
        .str.strip()
        .str.upper()
        .replace({"": "N"})
    )
    # Formatear CLIENTE sin .0 si es entero
    df["CLIENTE"] = df["CLIENTE"].apply(
        lambda x: str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else str(x)
    )
    # Formatear CANTIDAD sin .0 si es entero (y asegurar numérico para cálculos)
    df["CANTIDAD"] = pd.to_numeric(df["CANTIDAD"], errors="coerce")
    df["CANTIDAD"] = df["CANTIDAD"].fillna(0)
    df["CANTIDAD"] = df["CANTIDAD"].apply(lambda x: int(x) if float(x).is_integer() else x)
    return df

def update_picking_bulk(numero: int, sku_to_flag: list[tuple[str, str]]):
    if not sku_to_flag:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        "UPDATE sap SET PICKING = %s WHERE NUMERO = %s AND CODIGO = %s",
        [(flag, numero, codigo) for (codigo, flag) in sku_to_flag]
    )
    conn.commit()
    cur.close()
    conn.close()

# ================== STATE ==================
if "page" not in st.session_state:
    st.session_state.page = "list"
if "selected_pedido" not in st.session_state:
    st.session_state.selected_pedido = None

def go(page: str):
    st.session_state.page = page

# ================== PÁGINA: LISTA ==================
def page_list():
    st.title("📦 Pedidos (SAP)")
    c1, _ = st.columns([2,1])
    with c1:
        buscar = st.text_input("Buscar por cliente o número de pedido", placeholder="Ej: DIA o 100023120")
    orders_df = get_orders(buscar=buscar)

    st.subheader("Resultados")
    if orders_df.empty:
        st.info("No hay pedidos para mostrar.")
        return

    n_cols, idx, total = 3, 0, len(orders_df)
    while idx < total:
        cols = st.columns([1,1,1])
        for col in cols:
            if idx >= total: break
            row = orders_df.iloc[idx]
            numero, cliente = row.NUMERO, row.CLIENTE

            items = get_order_items(numero)
            total_items = len(items)
            picked = (items["PICKING"] == "Y").sum() if total_items > 0 else 0
            pct = int((picked / total_items) * 100) if total_items > 0 else 0

            with col:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"<h4>Pedido #{numero}</h4>", unsafe_allow_html=True)
                st.markdown(f"<div><small>Cliente:</small> <b>{cliente}</b></div>", unsafe_allow_html=True)
                st.progress(pct/100)
                st.caption(f"Picking: {picked}/{total_items} ({pct}%)")
                if st.button("Ver detalle", key=f"open_{numero}"):
                    st.session_state.selected_pedido = int(numero)
                    go("detail")
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

# ================== PÁGINA: DETALLE ==================
def page_detail():
    numero = st.session_state.selected_pedido
    if not numero:
        st.warning("No hay pedido seleccionado.")
        if st.button("Volver a pedidos"):
            go("list")
        return

    left, right = st.columns([3,1])
    with left:
        st.title(f"🧾 Detalle Pedido #{numero}")
    with right:
        st.write("")
        if st.button("⬅ Volver a pedidos", use_container_width=True):
            go("list")
            return

    items_df = get_order_items(numero)
    if items_df.empty:
        st.info("Este pedido no tiene ítems.")
        return

    # ========= Estado inicial por SKU (True si Y) =========
    for _, r in items_df.iterrows():
        key = f"pick_{numero}_{r['CODIGO']}"
        if key not in st.session_state:
            st.session_state[key] = (r["PICKING"] == "Y")

    # ========= Barra de avance por CANTIDADES (entre título y cliente) =========
    # Total por cantidades
    total_qty = pd.to_numeric(items_df["CANTIDAD"], errors="coerce").fillna(0).sum()
    # Cantidad "pickeada" segun el estado actual en la UI
    picked_qty = 0
    for _, r in items_df.iterrows():
        key = f"pick_{numero}_{r['CODIGO']}"
        if st.session_state.get(key, False):
            picked_qty += float(r["CANTIDAD"]) if r["CANTIDAD"] is not None else 0
    pct_qty = int((picked_qty / total_qty) * 100) if total_qty > 0 else 0

    st.progress((picked_qty / total_qty) if total_qty > 0 else 0.0)
    st.caption(f"Avance: {int(picked_qty) if picked_qty.is_integer() else picked_qty} / {int(total_qty) if float(total_qty).is_integer() else total_qty} ({pct_qty}%)")

    # ========= Cliente (debajo de la barra, como pediste) =========
    cliente = str(items_df["CLIENTE"].iloc[0])
    st.markdown(f"**Cliente:** {cliente}")

    # Cabecera de la grilla
    hc1, hc2, hc3 = st.columns([5,2,3])
    with hc1: st.markdown('<div class="detail-head">SKU</div>', unsafe_allow_html=True)
    with hc2: st.markdown('<div class="detail-head" style="text-align:right;">Cantidad</div>', unsafe_allow_html=True)
    with hc3: st.markdown('<div class="detail-head">Picking</div>', unsafe_allow_html=True)

    # Filas con botones Picking (toggle inmediato y la barra se actualiza al instante por st.rerun)
    for _, r in items_df.iterrows():
        key = f"pick_{numero}_{r['CODIGO']}"
        active = st.session_state[key]

        c1, c2, c3 = st.columns([5,2,3])
        with c1:
            st.markdown(f'<div class="detail-row">{r["CODIGO"]}</div>', unsafe_allow_html=True)
        with c2:
            # Mostrar cantidad sin .0 si es entero
            cant = r["CANTIDAD"]
            cant_str = str(int(cant)) if isinstance(cant, (int, float)) and float(cant).is_integer() else str(cant)
            st.markdown(f'<div class="detail-row" style="text-align:right;">{cant_str}</div>', unsafe_allow_html=True)
        with c3:
            btn_type = "primary" if active else "secondary"
            if st.button("Picking", key=f"btn_{key}", type=btn_type, use_container_width=True):
                st.session_state[key] = not active
                st.rerun()

    # Barra inferior
    st.markdown('<div class="confirm-bar">', unsafe_allow_html=True)
    ccf, _, _ = st.columns([1,1,2])
    with ccf:
        if st.button("Confirmar cambios", key="confirm", use_container_width=True, type="primary"):
            try:
                updates = []
                for _, r in items_df.iterrows():
                    logical_key = f"pick_{numero}_{r['CODIGO']}"
                    flag = "Y" if st.session_state[logical_key] else "N"
                    updates.append((str(r["CODIGO"]), flag))
                update_picking_bulk(numero, updates)
                st.success("Picking actualizado correctamente.")
                st.cache_data.clear()
                go("list")
                st.rerun()
            except Exception as e:
                st.error(f"Error al actualizar: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

# ================== ROUTER ==================
if st.session_state.page == "list":
    page_list()
elif st.session_state.page == "detail":
    page_detail()
