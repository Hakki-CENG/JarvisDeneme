from __future__ import annotations

from pathlib import Path

from app.services.policy_service import policy_service


class VisionService:
    def __init__(self) -> None:
        self._pytesseract = None
        self._image_cls = None

        try:
            import pytesseract
            from PIL import Image

            self._pytesseract = pytesseract
            self._image_cls = Image
        except Exception:
            self._pytesseract = None
            self._image_cls = None

    def ocr_image(self, image_path: str) -> dict[str, str]:
        path = Path(image_path).expanduser().resolve()
        if not policy_service.is_path_allowed(str(path)):
            return {'status': 'error', 'message': f'Image path is outside allowed roots: {path}'}
        if not path.exists():
            return {'status': 'error', 'message': f'File does not exist: {image_path}'}

        if not self._pytesseract or not self._image_cls:
            return {'status': 'ok', 'text': 'OCR dependencies are unavailable, returning placeholder text.'}

        image = self._image_cls.open(path)
        text = self._pytesseract.image_to_string(image)
        return {'status': 'ok', 'text': text}

    def ocr_layout(self, image_path: str) -> dict:
        path = Path(image_path).expanduser().resolve()
        if not policy_service.is_path_allowed(str(path)):
            return {'status': 'error', 'message': f'Image path is outside allowed roots: {path}'}
        if not path.exists():
            return {'status': 'error', 'message': f'File does not exist: {image_path}'}

        if not self._pytesseract or not self._image_cls:
            return {'status': 'ok', 'boxes': [], 'message': 'OCR dependencies unavailable'}

        image = self._image_cls.open(path)
        data = self._pytesseract.image_to_data(image, output_type=self._pytesseract.Output.DICT)
        boxes: list[dict] = []
        n = len(data.get('text', []))
        for i in range(n):
            text = str(data['text'][i]).strip()
            if not text:
                continue
            boxes.append(
                {
                    'text': text,
                    'left': int(data['left'][i]),
                    'top': int(data['top'][i]),
                    'width': int(data['width'][i]),
                    'height': int(data['height'][i]),
                    'confidence': float(data['conf'][i]) if str(data['conf'][i]).replace('.', '', 1).isdigit() else -1,
                }
            )
        return {'status': 'ok', 'boxes': boxes}

    def analyze_scene(self, image_path: str) -> dict:
        path = Path(image_path).expanduser().resolve()
        if not policy_service.is_path_allowed(str(path)):
            return {'status': 'error', 'message': f'Image path is outside allowed roots: {path}'}
        if not path.exists():
            return {'status': 'error', 'message': f'File does not exist: {image_path}'}
        if not self._image_cls:
            return {'status': 'ok', 'summary': 'Image library unavailable', 'width': 0, 'height': 0, 'text_tokens': 0}

        image = self._image_cls.open(path)
        width, height = image.size
        text = ''
        if self._pytesseract:
            try:
                text = self._pytesseract.image_to_string(image)
            except Exception:
                text = ''
        tokens = [token for token in text.split() if token]
        return {
            'status': 'ok',
            'width': width,
            'height': height,
            'text_tokens': len(tokens),
            'summary': (text[:500] if text else 'No OCR text extracted'),
        }


vision_service = VisionService()
