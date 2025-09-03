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
  border: 1px solid #e9e9e9;
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.04);
  background: #fff;
  height: 100%;
}
.card h4 { margin: 0 0 6px 0; font-size: 1rem; }
.card small { color: #666; }
.card .stButton>button { width: 100%; border-radius: 8px; padding: 6px 10px; }

/* Cabecera del detalle y filas */
.detail-head { font-weight: 600; opacity: 0.9; padding: 6px 4px; border-bottom: 1px solid #f0f0f0; }
.detail-row { border-bottom: 1px dashed #ececec; padding: 8px 4px; }

/* Botón visual de picking */
.picking-wrap {
  display: inline-block; border: 1px solid #d9d9d9; border-radius: 8px;
  padding: 4px 10px; cursor: pointer; user-select: none; background: #fff;
}
.picking-wrap.active { background: #d9f9d9; border-color: #97d897; font-weight: 600; }

/* Barra confirmar (pegada abajo del panel derecho) */
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
    """
    Devuelve pedidos (NUMERO) únicos con su CLIENTE.
    """
    base = """
        SELECT DISTINCT NUMERO, CLIENTE
        FROM sap
    """
    where = []
    params = []
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
    """
    Actualiza PICKING para cada (CODIGO -> 'Y'/'N') dentro del pedido NUMERO.
    sku_to_flag: [(codigo, 'Y'|'N'), ...]
    """
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
if "selected_pedido" not in st.session_state:
    st.session_state.selected_pedido = None

# ================== FILTROS SUPERIORES ==================
c1, c2 = st.columns([2,1])
with c1:
    buscar = st.text_input("Buscar por cliente o número de pedido", placeholder="Ej: DIA o 100023120")
with c2:
    st.write("")  # spacer

orders_df = get_orders(buscar=buscar)

# ================== LAYOUT: LISTA + DETALLE ==================
left, right = st.columns([2, 1])

with left:
    st.subheader("Pedidos")
    if orders_df.empty:
        st.info("No hay pedidos para mostrar.")
    else:
        n_cols = 3
        idx = 0
        total = len(orders_df)
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
                    st.markdown("</div>", unsafe_allow_html=True)
                idx += 1

with right:
    st.subheader("Detalle del pedido")
    sel = st.session_state.selected_pedido
    if not sel:
        st.info("Selecciona un pedido para ver su detalle.")
    else:
        items_df = get_order_items(sel)
        if items_df.empty:
            st.warning("Este pedido no tiene ítems.")
        else:
            # Inicializar estado por SKU
            for _, r in items_df.iterrows():
                key = f"pick_{sel}_{r['CODIGO']}"
                if key not in st.session_state:
                    st.session_state[key] = (str(r["PICKING"]).upper() == "Y")

            # Cabecera
            hc1, hc2, hc3 = st.columns([5, 2, 3])
            with hc1: st.markdown('<div class="detail-head">SKU</div>', unsafe_allow_html=True)
            with hc2: st.markdown('<div class="detail-head" style="text-align:right;">Cantidad</div>', unsafe_allow_html=True)
            with hc3: st.markdown('<div class="detail-head">Picking</div>', unsafe_allow_html=True)

            # Filas
            for _, r in items_df.iterrows():
                key = f"pick_{sel}_{r['CODIGO']}"
                active = st.session_state[key]
                c1, c2, c3 = st.columns([5, 2, 3])
                with c1:
                    st.markdown(f'<div class="detail-row">{r["CODIGO"]}</div>', unsafe_allow_html=True)
                with c2:
                    st.markdown(f'<div class="detail-row" style="text-align:right;">{r["CANTIDAD"]}</div>', unsafe_allow_html=True)
                with c3:
                    # Botón real que alterna el estado (sin experimental_rerun)
                    col_btn = st.container()
                    with col_btn:
                        # Indicador visual (verde si activo)
                        st.markdown(
                            f'<div class="picking-wrap {"active" if active else ""}">'
                            f'{"✔ Seleccionado" if active else "Marcar picking"}'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        if st.button(("Quitar" if active else "Marcar"), key=f"btn_{key}"):
                            st.session_state[key] = not st.session_state[key]

            # Confirmar / Desmarcar
            st.markdown('<div class="confirm-bar">', unsafe_allow_html=True)
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("Confirmar cambios", type="primary", use_container_width=True, key="confirm"):
                    try:
                        # Construir updates: para TODOS los ítems del pedido
                        updates = []
                        for _, r in items_df.iterrows():
                            key = f"pick_{sel}_{r['CODIGO']}"
                            flag = "Y" if st.session_state[key] else "N"
                            updates.append((str(r["CODIGO"]), flag))
                        # Guardar
                        update_picking_bulk(sel, [(codigo, flag) for (codigo, flag) in updates])
                        st.success("Picking actualizado correctamente.")
                        st.cache_data.clear()   # refresca caches de get_orders/get_order_items
                    except Exception as e:
                        st.error(f"Error al actualizar: {e}")
            with cc2:
                if st.button("Desmarcar todo", use_container_width=True, key="clear_all"):
                    for _, r in items_df.iterrows():
                        st.session_state[f"pick_{sel}_{r['CODIGO']}"] = False
                    st.info("Se desmarcaron todos los ítems.")
            st.markdown('</div>', unsafe_allow_html=True)
