import base64
import io
import qrcode
from qrcode.image.pil import PilImage


def generate_qr_image(url: str, box_size: int = 8, border: int = 2) -> io.BytesIO:
    """
    Generates a high-quality QR code image stream in PNG format encoding the given URL.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff", image_factory=PilImage)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer


def generate_qr_data_uri(url: str, box_size: int = 6, border: int = 2) -> str:
    """
    Generates a base64 data URI string (data:image/png;base64,...) for direct HTML or PDF rendering.
    """
    buffer = generate_qr_image(url, box_size=box_size, border=border)
    b64_encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{b64_encoded}"
