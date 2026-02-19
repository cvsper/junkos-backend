"""
File Upload API routes for Umuve.
Handles photo uploads for job documentation.
"""

import os
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import generate_uuid
from auth_routes import require_auth

upload_bp = Blueprint("upload", __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_FILES = 10
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


def _allowed_file(filename):
    """Check if a filename has an allowed extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _ensure_upload_dir():
    """Create the uploads directory if it does not exist."""
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------------------------------------------------------
# POST /api/upload/photos  (auth required)
# ---------------------------------------------------------------------------
@upload_bp.route("/api/upload/photos", methods=["POST"])
@require_auth
def upload_photos(user_id):
    """
    Upload one or more photos (multipart/form-data).

    Form field: files (multiple)
    Constraints:
        - Max 10 files per request
        - Max 10 MB per file
        - Allowed types: jpg, jpeg, png, webp
    Returns: { success, urls: [ ... ] }
    """
    if "files" not in request.files:
        return jsonify({"error": "No files provided. Use the 'files' form field."}), 400

    files = request.files.getlist("files")

    if len(files) == 0:
        return jsonify({"error": "No files provided"}), 400

    if len(files) > MAX_FILES:
        return jsonify({"error": "Maximum {} files allowed per upload".format(MAX_FILES)}), 400

    _ensure_upload_dir()

    urls = []
    errors = []

    for file in files:
        if not file or not file.filename:
            errors.append({"file": "unknown", "error": "Empty file"})
            continue

        if not _allowed_file(file.filename):
            errors.append({
                "file": file.filename,
                "error": "File type not allowed. Accepted: jpg, png, webp",
            })
            continue

        # Check file size by reading content length
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        if size > MAX_FILE_SIZE:
            errors.append({
                "file": file.filename,
                "error": "File exceeds maximum size of 10 MB",
            })
            continue

        # Generate unique filename to avoid collisions
        ext = file.filename.rsplit(".", 1)[1].lower()
        unique_name = "{}.{}".format(generate_uuid(), ext)
        safe_name = secure_filename(unique_name)
        filepath = os.path.join(UPLOAD_FOLDER, safe_name)

        file.save(filepath)

        # Build public URL
        url = "/uploads/{}".format(safe_name)
        urls.append(url)

    response = {"success": True, "urls": urls}
    if errors:
        response["errors"] = errors

    status_code = 201 if urls else 400
    if not urls and errors:
        response["success"] = False
        response["error"] = "No files were uploaded successfully"

    return jsonify(response), status_code


# ---------------------------------------------------------------------------
# GET /uploads/<filename>  (public -- serve uploaded files)
# ---------------------------------------------------------------------------
@upload_bp.route("/uploads/<filename>", methods=["GET"])
def serve_upload(filename):
    """Serve a previously uploaded file."""
    safe_name = secure_filename(filename)
    if not os.path.exists(os.path.join(UPLOAD_FOLDER, safe_name)):
        return jsonify({"error": "File not found"}), 404

    return send_from_directory(UPLOAD_FOLDER, safe_name)
