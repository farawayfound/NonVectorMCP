# -*- coding: utf-8 -*-
"""
Incremental VPO RAG Indexer
- Tracks processed documents with checksums and timestamps
- Only processes new/modified files
- Maintains existing vector database structure
- Supports topic-based organization
"""

import os, json, hashlib, datetime
from pathlib import Path
from typing import Dict, List, Any
import logging

class IncrementalIndexer:
    def __init__(self, out_dir: str):
        self.out_dir = Path(out_dir)
        self.state_file = self.out_dir / "state" / "processing_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._cleanup_tmp_files()
        self.state = self._load_state()

    def _cleanup_tmp_files(self):
        """Remove any orphaned .tmp files left by a previously killed build."""
        for pattern in ['detail/chunks.*.jsonl.tmp', 'router/*.jsonl.tmp']:
            for tmp in self.out_dir.glob(pattern):
                try:
                    tmp.unlink()
                    logging.info(f"Cleaned up orphaned temp file: {tmp.name}")
                except OSError:
                    pass
        
    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"processed_files": {}, "last_run": None, "version": "1.0"}
    
    def _save_state(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
    
    def _get_file_hash(self, file_path: Path) -> str:
        stat = file_path.stat()
        content_hash = hashlib.md5()
        content_hash.update(f"{stat.st_size}:{stat.st_mtime}".encode())
        
        if stat.st_size < 10 * 1024 * 1024:
            try:
                with open(file_path, 'rb') as f:
                    content_hash.update(f.read())
            except Exception:
                pass
                
        return content_hash.hexdigest()
    
    def get_files_to_process(self, source_dir: str) -> Dict[str, List[Path]]:
        files_to_process = {"new": [], "modified": [], "unchanged": []}
        
        src_path = Path(source_dir)
        all_files = []
        if src_path.exists():
            all_files.extend(src_path.glob("**/*.pdf"))
            all_files.extend(src_path.glob("**/*.pptx"))
            all_files.extend(src_path.glob("**/*.txt"))
            all_files.extend(src_path.glob("**/*.docx"))
            all_files.extend(src_path.glob("**/*.csv"))
        
        for file_path in all_files:
            file_key = str(file_path.resolve())
            current_hash = self._get_file_hash(file_path)
            
            if file_key not in self.state["processed_files"]:
                files_to_process["new"].append(file_path)
                logging.info(f"New file: {file_path.name}")
            elif self.state["processed_files"][file_key]["hash"] != current_hash:
                files_to_process["modified"].append(file_path)
                logging.info(f"Modified file: {file_path.name}")
            else:
                files_to_process["unchanged"].append(file_path)
        
        return files_to_process
    
    def mark_processed(self, file_path: Path, doc_ids: List[str]):
        file_key = str(file_path.resolve())
        self.state["processed_files"][file_key] = {
            "hash": self._get_file_hash(file_path),
            "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "doc_ids": doc_ids,
            "file_name": file_path.name
        }
    
    def get_existing_doc_ids(self, file_path: Path) -> List[str]:
        file_key = str(file_path.resolve())
        return self.state["processed_files"].get(file_key, {}).get("doc_ids", [])
    
    def remove_old_records(self, doc_ids: List[str]):
        doc_id_set = set(doc_ids)

        # Remove from router files atomically
        for jsonl_file in ["router/router.docs.jsonl", "router/router.chapters.jsonl"]:
            file_path = self.out_dir / jsonl_file
            if not file_path.exists():
                continue
            existing_records = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        if self._extract_doc_id(record, jsonl_file) not in doc_id_set:
                            existing_records.append(record)
            tmp = file_path.with_suffix('.jsonl.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                for record in existing_records:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
            tmp.replace(file_path)

        # Remove from category-specific chunk files atomically
        detail_dir = self.out_dir / "detail"
        for category_file in detail_dir.glob("chunks.*.jsonl"):
            if category_file.suffix == '.tmp':
                continue
            existing_records = []
            with open(category_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        if record.get("metadata", {}).get("doc_id", "") not in doc_id_set:
                            existing_records.append(record)
            tmp = category_file.with_name(category_file.name + '.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                for record in existing_records:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
            tmp.replace(category_file)
    
    def _extract_doc_id(self, record: Dict, file_type: str) -> str:
        if "router" in file_type:
            route_id = record.get("route_id", "")
            return route_id.split("::")[0] if "::" in route_id else route_id
        else:
            return record.get("metadata", {}).get("doc_id", "")
    
    def append_new_records(self, new_records: Dict[str, List[Dict]]):
        file_mapping = {
            "router_docs": "router/router.docs.jsonl",
            "router_chapters": "router/router.chapters.jsonl", 
            "detail": "detail/chunks.jsonl"
        }
        
        for record_type, records in new_records.items():
            if not records:
                continue
                
            file_path = self.out_dir / file_mapping[record_type]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'a', encoding='utf-8') as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
    
    def finalize_run(self):
        self.state["last_run"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._save_state()
        logging.info(f"Incremental processing complete. State saved to {self.state_file}")