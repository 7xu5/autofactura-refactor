"""
tests/test_invoices_routes.py
==============================
Tests de caracterización a nivel HTTP para blueprints/invoices/views.py.

Mockeamos VerifactuOrchestrator.emitir_y_enviar_factura en todos los casos:
no queremos firmar certificados reales ni golpear la AEAT en estos tests.
También capturamos las llamadas a qrcode.make() para verificar el contenido
exacto de la URL del QR, sin generar la imagen real.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from blueprints.invoices import views as invoices_views
from models import Factura, FacturaVerifactu, db
from conftest import crear_factura_db
import qrcode
# ---------------------------------------------------------------------------
# factura_crear
# ---------------------------------------------------------------------------

class TestFacturaCrear:

    def test_get_devuelve_200(self, auth_client, configuracion, cliente):
        resp = auth_client.get("/facturas/crear")
        assert resp.status_code == 200

    def test_post_sin_cliente_no_crea_factura(self, auth_client, configuracion, cliente):
        resp = auth_client.post("/facturas/crear", data={
            "contacto_id": "",
            "lineas_count": "1",
            "concepto_1": "Algo",
            "unidades_1": "1",
            "precio_1": "10",
        })
        assert resp.status_code == 200  # re-renderiza el formulario, no redirige
        assert Factura.query.count() == 0

    def test_post_numero_duplicado_no_crea_factura(self, auth_client, configuracion, cliente):
        crear_factura_db(cliente, numero="F26-001")
        resp = auth_client.post("/facturas/crear", data={
            "contacto_id": str(cliente.id),
            "numero_factura": "F26-001",
            "fecha_factura": "2026-06-10",
            "lineas_count": "1",
            "concepto_1": "Algo",
            "unidades_1": "1",
            "precio_1": "10",
            "impuesto_1": "21% IVA",
        })
        assert resp.status_code == 200
        assert Factura.query.count() == 1

    def test_post_borrador_no_llama_a_verifactu(self, auth_client, configuracion, cliente):
        with patch.object(invoices_views.VerifactuOrchestrator, "emitir_y_enviar_factura") as mock_vf:
            resp = auth_client.post("/facturas/crear", data={
                "contacto_id": str(cliente.id),
                "fecha_factura": "2026-06-10",
                "guardar_borrador": "on",
                "lineas_count": "1",
                "concepto_1": "Servicio borrador",
                "unidades_1": "2",
                "precio_1": "100",
                "impuesto_1": "21% IVA",
            })
        assert resp.status_code == 302
        mock_vf.assert_not_called()
        
        factura = Factura.query.first()
        # 💡 SOLUCIÓN: un assert explícito asegura a Pylance que no es None
        assert factura is not None
        assert factura.tipo_pestana == "Borrador"
        assert factura.total_base_imponible == Decimal("200.00")
        assert factura.total_cuota_iva == Decimal("42.00")
        assert factura.total_factura == Decimal("242.00")

    def test_post_emitida_con_password_llama_a_verifactu(self, auth_client, configuracion, cliente):
        configuracion.ruta_certificado = "certs/fake.pfx"
        db.session.commit()
        with patch.object(
            invoices_views.VerifactuOrchestrator, "emitir_y_enviar_factura",
            return_value=(True, "OK"),
        ) as mock_vf:
            resp = auth_client.post("/facturas/crear", data={
                "contacto_id": str(cliente.id),
                "fecha_factura": "2026-06-10",
                "lineas_count": "1",
                "concepto_1": "Servicio emitido",
                "unidades_1": "1",
                "precio_1": "100",
                "impuesto_1": "21% IVA",
                "cert_password": "secreto123",
            })
        assert resp.status_code == 302
        mock_vf.assert_called_once()
        
        factura = Factura.query.first()
        assert factura is not None
        factura_id_llamada = mock_vf.call_args[0][0]
        assert factura_id_llamada == factura.id

    def test_post_emitida_sin_password_no_llama_a_verifactu(self, auth_client, configuracion, cliente):
        with patch.object(invoices_views.VerifactuOrchestrator, "emitir_y_enviar_factura") as mock_vf:
            resp = auth_client.post("/facturas/crear", data={
                "contacto_id": str(cliente.id),
                "fecha_factura": "2026-06-10",
                "lineas_count": "1",
                "concepto_1": "Servicio sin firmar",
                "unidades_1": "1",
                "precio_1": "100",
                "impuesto_1": "21% IVA",
            })
        assert resp.status_code == 302
        mock_vf.assert_not_called()


# ---------------------------------------------------------------------------
# factura_rectificar
# ---------------------------------------------------------------------------

class TestFacturaRectificar:

    def test_rectificar_borrador_devuelve_400(self, auth_client, configuracion, cliente):
        factura = crear_factura_db(cliente, estado_ui="Borrador")
        resp = auth_client.post(f"/facturas/{factura.id}/rectificar", data={})
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_rectificar_emitida_invierte_signos(self, auth_client, configuracion, cliente):
        original = crear_factura_db(
            cliente, numero="F26-005", unidades=Decimal("3"), precio=Decimal("50"), estado_ui="Emitida"
        )
        resp = auth_client.post(
            f"/facturas/{original.id}/rectificar",
            data={"motivo_rectificacion": "Error material"},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True

        rectificativa = db.session.get(Factura, payload["new_id"])
        assert rectificativa is not None
        assert rectificativa.tipo_factura == "Rectificativa"
        assert rectificativa.estado_ui == "Borrador"
        assert rectificativa.factura_rectificada_id == original.id
        assert rectificativa.total_base_imponible == -original.total_base_imponible
        assert rectificativa.total_factura == -original.total_factura
        
        # 💡 SOLUCIÓN: Casteamos ambas relaciones a listas reales de Python
        lineas_rectificativa = list(rectificativa.lineas) # type: ignore
        lineas_original = list(original.lineas) # type: ignore

        assert lineas_rectificativa[0].unidades == -lineas_original[0].unidades
        assert lineas_rectificativa[0].concepto.startswith(f"Rectificación {original.numero_factura}:")


# ---------------------------------------------------------------------------
# factura_eliminar / factura_cobrar / factura_duplicar
# ---------------------------------------------------------------------------

class TestAccionesSimples:

    def test_eliminar_borra_la_factura(self, auth_client, configuracion, cliente):
        factura = crear_factura_db(cliente)
        resp = auth_client.post(f"/facturas/{factura.id}/eliminar")
        assert resp.status_code == 200
        assert db.session.get(Factura, factura.id) is None

    def test_cobrar_actualiza_estado_contable(self, auth_client, configuracion, cliente):
        factura = crear_factura_db(cliente)
        resp = auth_client.post(f"/facturas/{factura.id}/cobrar")
        assert resp.status_code == 200
        assert resp.get_json()["estado_pago"] == "Cobrada"
        db.session.refresh(factura)
        assert factura.estado_contable == "Cobrada"

    def test_duplicar_crea_copia_en_borrador(self, auth_client, configuracion, cliente):
        original = crear_factura_db(cliente, numero="F26-010")
        resp = auth_client.post(f"/facturas/{original.id}/duplicar")
        assert resp.status_code == 200
        payload = resp.get_json()
        
        nueva = db.session.get(Factura, payload["new_id"])
        assert nueva is not None
        assert nueva.id != original.id
        assert nueva.tipo_pestana == "Borrador"
        assert nueva.numero_factura == payload["new_numero"]
        
        # 💡 SOLUCIÓN: Usamos variables correspondientes a este test ('nueva' y 'original')
        lineas_nueva = list(nueva.lineas) # type: ignore
        lineas_original = list(original.lineas) # type: ignore

        assert lineas_nueva[0].unidades == lineas_original[0].unidades


# ---------------------------------------------------------------------------
# QR — divergencias conocidas entre factura_editar y factura_descargar
# ---------------------------------------------------------------------------

class _FakeQRImage:
    """Sustituye al objeto qrcode.image.pil.PilImage para no generar PNGs reales."""

    def __init__(self, data):
        self.data = data

    def save(self, buf, **kwargs):
        buf.write(b"FAKEPNGDATA")


class TestDivergenciaQR:
    """
    HALLAZGO: en la práctica solo factura_descargar genera un QR real para
    el usuario. El bloque de QR de factura_editar es código muerto (ver
    test_editar_redirige_si_aceptada_dejando_el_bloque_qr_inalcanzable):
    la guarda al inicio de la función redirige antes de llegar a esa rama
    para facturas con verifactu_estado == 'Aceptado', que es justo la
    única condición bajo la que ese bloque se ejecutaría.
    """

    def test_editar_redirige_si_aceptada_dejando_el_bloque_qr_inalcanzable(
        self, auth_client, configuracion, cliente, monkeypatch
    ):
        factura = crear_factura_db(cliente, verifactu_estado="Aceptado")
        captured = {}
        monkeypatch.setattr(qrcode, "make", lambda data: captured.update(url=data))
        resp = auth_client.get(f"/facturas/{factura.id}/editar")
        assert resp.status_code == 302
        assert "url" not in captured  # qrcode.make() nunca llega a invocarse

    def test_descargar_genera_qr_con_nif_normalizado_y_total_abs(
        self, auth_client, configuracion, cliente, monkeypatch
    ):
        factura = crear_factura_db(cliente)
        vf = FacturaVerifactu(
            factura_id=factura.id,
            fecha_hora_alta=datetime(2026, 6, 10, 12, 0, 0),
            hash_actual="a" * 64,
            xml_firmado="<xml/>",
            estado_envio="Enviado_Aceptado",
        )
        db.session.add(vf)
        db.session.commit()

        captured = {}

        def fake_make(data):
            captured["url"] = data
            return _FakeQRImage(data)

        monkeypatch.setattr(qrcode, "make", fake_make)

        resp = auth_client.get(f"/facturas/{factura.id}/descargar")
        assert resp.status_code == 200
        assert "url" in captured
        assert "nif=B12345678" in captured["url"]
        assert f"total={abs(float(factura.total_factura)):.2f}" in captured["url"]

    def test_editar_no_genera_qr_si_no_esta_aceptado(
        self, auth_client, configuracion, cliente, monkeypatch
    ):
        factura = crear_factura_db(cliente, verifactu_estado="Pendiente")
        captured = {}
        monkeypatch.setattr(
            qrcode, "make",
            lambda data: captured.update(url=data) or _FakeQRImage(data),
        )
        resp = auth_client.get(f"/facturas/{factura.id}/editar")
        assert resp.status_code == 200
        assert "url" not in captured

    def test_descargar_no_genera_qr_si_no_hay_registro_verifactu(
        self, auth_client, configuracion, cliente, monkeypatch
    ):
        factura = crear_factura_db(cliente)  # sin FacturaVerifactu asociado
        captured = {}
        monkeypatch.setattr(
            qrcode, "make",
            lambda data: captured.update(url=data) or _FakeQRImage(data),
        )
        resp = auth_client.get(f"/facturas/{factura.id}/descargar")
        assert resp.status_code == 200
        assert "url" not in captured


# ---------------------------------------------------------------------------
# factura_descargar / factura_previsualizar — smoke tests de generación de PDF
# ---------------------------------------------------------------------------

class TestGeneracionPDF:

    def test_descargar_devuelve_pdf(self, auth_client, configuracion, cliente):
        factura = crear_factura_db(cliente)
        resp = auth_client.get(f"/facturas/{factura.id}/descargar")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/pdf"

    def test_descargar_factura_sin_lineas_usa_fallback(self, auth_client, configuracion, cliente):
        factura = Factura(
            numero_factura="F26-099",
            contacto_id=cliente.id,
            fecha_factura=date(2026, 6, 1),
            tipo_pestana="Emitida",
            estado_ui="Emitida",
            estado_contable="Pendiente",
            total_base_imponible=Decimal("100.00"),
            total_cuota_iva=Decimal("21.00"),
            total_factura=Decimal("121.00"),
        )
        db.session.add(factura)
        db.session.commit()

        resp = auth_client.get(f"/facturas/{factura.id}/descargar")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/pdf"

    def test_previsualizar_sin_cliente_devuelve_400(self, auth_client, configuracion):
        resp = auth_client.post("/facturas/previsualizar", data={})
        assert resp.status_code == 400

    def test_previsualizar_con_cliente_devuelve_pdf(self, auth_client, configuracion, cliente):
        resp = auth_client.post("/facturas/previsualizar", data={
            "contacto_id": str(cliente.id),
            "fecha_factura": "2026-06-10",
            "fecha_vencimiento": "2026-07-10",
            "concepto_1": "Servicio previsualizado",
            "unidades_1": "1",
            "precio_1": "150",
            "descuento_1": "0",
            "impuesto_1": "21% IVA",
        })
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/pdf"