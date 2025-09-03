import streamlit as st
import pandas as pd
import mysql.connector

# ================== CONFIG ==================
st.set_page_config(page_title="Picking - Pedidos (SAP)", layout="wide")

# ================== ESTILOS ==================
st.markdown("""
<style>
.block-container { padding-top: 0.75rem; }

/* Tarjetas */
.card {
  border: 1px solid #e9e9e9; border-radius: 12px; padding: 12px 14px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.04); background: #fff; height: 100%;
}
.card h4 { margin: 0 0 6px 0; font-size: 1rem; }
.card small { color: #666; }
.card .stButton>button { width: 100%; border-radius: 8px; padding: 6px 10px; }

/* Tabla de detalle */
.detail-head { font-weight: 600; opacity: 0.9; padding: 6px 4px; border-bottom: 1px solid #f0f0f0; }
.detail-row { border-bottom: 1px dashed #ececec; padding: 8px 4px; }

/* Botón visual de picking (se ve como botón y cambia a verde si activo) */
.picking-btn {
  display:inline-block; border:1px solid #d9d9d9; border-radius: 8px;
  padding:6px 12px; background:#ffffff; font-weight:500; text-align:center; min-width:120px;
}
.picking-btn.active { background:#d9f9d9; border-color:#97d897; }

/* Barra confirmar (pegada abajo) */
.confirm-bar {
  position: sticky; bottom: 0; background: #fafafa; border-top: 1px solid #eee;
  padding: 10px; border-radius: 10px; margin-top: 8px;
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

# ================== STATE (router simple) ==================
if "page" not in st.session_state:
    st.session_state.page = "list"  # "list" | "detail"
if "selected_pedido" not in st.session_state:
    st.session_state.selected_pedido = None

def go(page: str):
    st.session_state.page = page

# ================== PÁGINA: LISTA DE PEDIDOS ==================
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
        cols = st.columns(n_cols)
        for col in cols:
            if idx >= total: break
            row = orders_df.iloc[idx]
            with col:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"""
                    <h4>Pedido #{row.NUMERO}</h4>
                    <div><small>Cliente:</small> <b>{row.CLIENTE}</b></div>
                """, unsafe_allow_html=True)
                if st.button("Ver detalle", key=f"open_{row.NUMERO}"):
                    st.session_state.selected_pedido = int(row.NUMERO)
                    go("detail")
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

# ================== PÁGINA: DETALLE (FULL PAGE) ==================
def page_detail():
    numero = st.session_state.selected_pedido
    if not numero:
        st.warning("No hay pedido seleccionado.")
        if st.button("Volver a pedidos"):
            go("list")
        return

    left, right = st.columns([1,1])
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

    cliente = items_df["CLIENTE"].iloc[0]
    st.markdown(f"**Cliente:** {cliente}")

    # Inicializar estado por SKU (True = verde/Y)
    for _, r in items_df.iterrows():
        key = f"pick_{numero}_{r['CODIGO']}"
        if key not in st.session_state:
            st.session_state[key] = (str(r["PICKING"]).upper() == "Y")

    # Cabecera
    hc1, hc2, hc3 = st.columns([5, 2, 3])
    with hc1: st.markdown('<div class="detail-head">SKU</div>', unsafe_allow_html=True)
    with hc2: st.markdown('<div class="detail-head" style="text-align:right;">Cantidad</div>', unsafe_allow_html=True)
    with hc3: st.markdown('<div class="detail-head">Picking</div>', unsafe_allow_html=True)

    # Filas
    for _, r in items_df.iterrows():
        key = f"pick_{numero}_{r['CODIGO']}"
        active = st.session_state[key]
        c1, c2, c3 = st.columns([5, 2, 3])
        with c1:
            st.markdown(f'<div class="detail-row">{r["CODIGO"]}</div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="detail-row" style="text-align:right;">{r["CANTIDAD"]}</div>', unsafe_allow_html=True)
        with c3:
            # Botón VISUAL (verde si activo) + botón funcional para alternar (siempre dice "Picking")
            st.markdown(
                f'<div class="picking-btn {"active" if active else ""}">Picking</div>',
                unsafe_allow_html=True
            )
            if st.button("Picking", key=f"btn_{key}"):
                st.session_state[key] = not st.session_state[key]

    # Confirmar / Desmarcar
    st.markdown('<div class="confirm-bar">', unsafe_allow_html=True)
    ccf, ccd, _ = st.columns([1,1,2])
    with ccf:
        if st.button("Confirmar cambios", type="primary", use_container_width=True, key="confirm"):
            try:
                updates = []
                for _, r in items_df.iterrows():
                    k = f"pick_{numero}_{r['CODIGO']}"
                    flag = "Y" if st.session_state[k] else "N"
                    updates.append((str(r["CODIGO"]), flag))
                update_picking_bulk(numero, [(codigo, flag) for (codigo, flag) in updates])
                st.success("Picking actualizado correctamente.")
                st.cache_data.clear()  # refresca caches
            except Exception as e:
                st.error(f"Error al actualizar: {e}")
    with ccd:
        if st.button("Desmarcar todo", use_container_width=True, key="clear_all"):
            for _, r in items_df.iterrows():
                st.session_state[f"pick_{numero}_{r['CODIGO']}"] = False
            st.info("Se desmarcaron todos los ítems.")

# ================== ROUTER ==================
if st.session_state.page == "list":
    page_list()
elif st.session_state.page == "detail":
    page_detail()
