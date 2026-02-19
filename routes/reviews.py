"""
Customer Reviews API routes for Umuve.
Allows customers to rate and review completed jobs.
"""

from flask import Blueprint, request, jsonify
from sqlalchemy import func

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, User, Job, Contractor, Review, generate_uuid, utcnow
from auth_routes import require_auth

reviews_bp = Blueprint("reviews", __name__, url_prefix="/api/reviews")


# ---------------------------------------------------------------------------
# POST /api/reviews — Create a review
# ---------------------------------------------------------------------------
@reviews_bp.route("", methods=["POST"])
@require_auth
def create_review(user_id):
    """Create a review for a completed job.

    Body JSON:
        job_id: str (required)
        rating: int 1-5 (required)
        comment: str (optional)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    job_id = data.get("job_id")
    rating = data.get("rating")
    comment = data.get("comment", "").strip() if data.get("comment") else None

    if not job_id:
        return jsonify({"error": "job_id is required"}), 400

    if rating is None:
        return jsonify({"error": "rating is required"}), 400

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be an integer"}), 400

    if not (1 <= rating <= 5):
        return jsonify({"error": "rating must be between 1 and 5"}), 400

    # Verify job exists, belongs to user, and is completed
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job.customer_id != user_id:
        return jsonify({"error": "Not authorized"}), 403
    if job.status != "completed":
        return jsonify({"error": "Can only review completed jobs"}), 400
    if not job.driver_id:
        return jsonify({"error": "No driver assigned to this job"}), 400

    # Check for duplicate review
    existing = Review.query.filter_by(job_id=job_id).first()
    if existing:
        return jsonify({"error": "This job has already been reviewed"}), 400

    # Find contractor
    contractor = Contractor.query.filter_by(user_id=job.driver_id).first()
    if not contractor:
        contractor = db.session.get(Contractor, job.driver_id)
    if not contractor:
        return jsonify({"error": "Contractor not found"}), 400

    review = Review(
        id=generate_uuid(),
        job_id=job_id,
        customer_id=user_id,
        contractor_id=contractor.id,
        rating=rating,
        comment=comment,
    )
    db.session.add(review)

    # Update contractor average rating
    avg = db.session.query(func.avg(Review.rating)).filter_by(
        contractor_id=contractor.id
    ).scalar()
    if avg is not None:
        # Include the new review in the average
        total_reviews = Review.query.filter_by(contractor_id=contractor.id).count()
        contractor.avg_rating = round(
            ((avg * (total_reviews - 1)) + rating) / total_reviews, 2
        )
    else:
        contractor.avg_rating = float(rating)

    db.session.commit()

    return jsonify({"success": True, "review": review.to_dict()}), 201


# ---------------------------------------------------------------------------
# GET /api/reviews/job/<job_id> — Get review for a specific job
# ---------------------------------------------------------------------------
@reviews_bp.route("/job/<job_id>", methods=["GET"])
def get_job_review(job_id):
    """Get the review for a specific job (if one exists)."""
    review = Review.query.filter_by(job_id=job_id).first()
    if not review:
        return jsonify({"success": True, "review": None}), 200

    return jsonify({"success": True, "review": review.to_dict()}), 200


# ---------------------------------------------------------------------------
# GET /api/reviews/contractor/<contractor_id> — Get all reviews for a contractor
# ---------------------------------------------------------------------------
@reviews_bp.route("/contractor/<contractor_id>", methods=["GET"])
def get_contractor_reviews(contractor_id):
    """Get all reviews for a contractor (public)."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = Review.query.filter_by(contractor_id=contractor_id).order_by(
        Review.created_at.desc()
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    avg_rating = db.session.query(func.avg(Review.rating)).filter_by(
        contractor_id=contractor_id
    ).scalar()
    total_reviews = Review.query.filter_by(contractor_id=contractor_id).count()

    return jsonify({
        "success": True,
        "reviews": [r.to_dict() for r in pagination.items],
        "avg_rating": round(float(avg_rating), 2) if avg_rating else 0.0,
        "total_reviews": total_reviews,
        "page": page,
        "pages": pagination.pages,
    }), 200
