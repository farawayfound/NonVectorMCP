# -*- coding: utf-8 -*-
"""
OCR processing for images in documents
"""
import logging
from typing import Dict, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import pytesseract
    from PIL import Image
    import io
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    logging.warning("pytesseract not installed - OCR disabled")

def extract_text_from_image(image_bytes: bytes, config: Dict) -> str:
    """Extract text from image bytes using OCR"""
    if not HAS_OCR:
        return ""
    
    try:
        tesseract_path = config.get('TESSERACT_PATH')
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        
        image = Image.open(io.BytesIO(image_bytes))
        
        min_size = config.get('OCR_MIN_IMAGE_SIZE', (100, 100))
        if image.size[0] < min_size[0] or image.size[1] < min_size[1]:
            return ""
        
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        
        lang = config.get('OCR_LANGUAGES', 'eng')
        text = pytesseract.image_to_string(image, lang=lang)
        
        return text.strip()
    
    except Exception as e:
        logging.warning(f"OCR failed: {e}")
        return ""

def _process_single_image(doc, task, config):
    """Process single image for parallel execution"""
    page_num, img_index, img, page = task
    try:
        xref = img[0]
        base_image = doc.extract_image(xref)
        text = extract_text_from_image(base_image["image"], config)
        
        if text:
            return {
                "page": page_num + 1,
                "image_index": img_index,
                "text": text,
                "bbox": page.get_image_bbox(img)
            }
    except Exception as e:
        logging.debug(f"Image extraction failed: {e}")
        return None

def process_pdf_images(doc, config: Dict) -> List[Dict]:
    """Extract and OCR all images from PDF with parallel processing"""
    if not config.get('ENABLE_OCR', False) or not HAS_OCR:
        return []
    
    image_tasks = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        
        for img_index, img in enumerate(image_list):
            image_tasks.append((page_num, img_index, img, page))
    
    if not image_tasks:
        return []
    
    max_workers = config.get('PARALLEL_OCR_WORKERS', 4)
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_single_image, doc, task, config): task 
            for task in image_tasks
        }
        
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    
    if results:
        logging.info(f"OCR extracted text from {len(results)}/{len(image_tasks)} images")
    
    return results

def process_docx_images(doc, config: Dict) -> List[Dict]:
    """Extract and OCR images from DOCX"""
    if not config.get('ENABLE_OCR', False) or not HAS_OCR:
        return []
    
    results = []
    
    try:
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    image_bytes = rel.target_part.blob
                    text = extract_text_from_image(image_bytes, config)
                    
                    if text:
                        results.append({
                            "text": text,
                            "type": "embedded_image"
                        })
                except Exception as e:
                    logging.debug(f"DOCX image OCR failed: {e}")
                    continue
    except Exception as e:
        logging.warning(f"DOCX image extraction failed: {e}")
    
    if results:
        logging.info(f"OCR extracted text from {len(results)} DOCX images")
    
    return results

def process_pptx_images(prs, config: Dict) -> List[Dict]:
    """Extract and OCR images from PPTX"""
    if not config.get('ENABLE_OCR', False) or not HAS_OCR:
        return []
    
    results = []
    
    for slide_num, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if hasattr(shape, "image"):
                try:
                    image_bytes = shape.image.blob
                    text = extract_text_from_image(image_bytes, config)
                    
                    if text:
                        results.append({
                            "slide": slide_num,
                            "text": text
                        })
                except Exception as e:
                    logging.debug(f"PPTX image OCR failed: {e}")
                    continue
    
    if results:
        logging.info(f"OCR extracted text from {len(results)} PPTX images")
    
    return results
