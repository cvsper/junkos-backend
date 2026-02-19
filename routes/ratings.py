"""
Rating API routes for Umuve.
"""

from flask import Blueprint, request, jsonify

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, Rating, Job, User, Contractor, Notification, generate_uuid
from auth_routes import require_auth

ratings_bp = Blueprint("ratings", __name__, url_prefix="/api/ratings")


@ratings_bp.route("", methods=["POST"])
@require_auth
def submit_rating(user_id):
    """
    Submit a rating for a completed job.
    Body JSON: job_id (str), stars (int 1-5), comment (str or null)
    """
    data = request.get_json() or {}

    job_id = data.get("job_id")
    stars = data.get("stars")
    comment = data.get("comment")

    if not job_id:
        return jsonify({"error": "job_id is required"}), 400
    if stars is None:
        return jsonify({"error": "stars is required"}), 400
    try:
        stars = int(stars)
    except (TypeError, ValueError):
        return jsonify({"error": "stars must be an integer"}), 400
    if stars < 1 or stars > 5:
        return jsonify({"error": "stars must be between 1 and 5"}), 400

    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job.status != "completed":
        return jsonify({"error": "Ratings can only be submitted for completed jobs"}), 409

    existing = Rating.query.filter_by(job_id=job_id, from_user_id=user_id).first()
    if existing:
        return jsonify({"error": "You have already rated this job"}), 409

    # Determine the recipient
    if user_id == job.customer_id:
        if not job.driver_id:
            return jsonify({"error": "No driver assigned to this job"}), 400
        to_user_id = db.session.get(Contractor, job.driver_id).user_id
    else:
        to_user_id = job.customer_id

    rating = Rating(
        id=generate_uuid(),
        job_id=job_id,
        from_user_id=user_id,
        to_user_id=to_user_id,
        stars=stars,
        comment=comment,
    )
    db.session.add(rating)

    # Update contractor avg_rating when a customer rates a driver
    if user_id == job.customer_id and job.driver_id:
        contractor = db.session.get(Contractor, job.driver_id)
        if contractor:
            all_ratings = (
                Rating.query
                .join(Job, Rating.job_id == Job.id)
                .filter(Job.driver_id == contractor.id, Rating.from_user_id == Job.customer_id)
                .all()
            )
            total_stars = sum(r.stars for r in all_ratings) + stars
            count = len(all_ratings) + 1
            contractor.avg_rating = round(total_stars / count, 2)

    notification = Notification(
        id=generate_uuid(),
        user_id=to_user_id,
        type="rating",
        title="New Rating Received",
        body="You received a {}-star rating.".format(stars),
        data={"job_id": job_id, "stars": stars},
    )
    db.session.add(notification)

    db.session.commit()
    return jsonify({"success": True, "rating": rating.to_dict()}), 201


@ratings_bp.route("/user/<target_user_id>", methods=["GET"])
def get_user_ratings(target_user_id):
    """Return all ratings received by a user."""
    user = db.session.get(User, target_user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    pagination = (
        Rating.query
        .filter_by(to_user_id=target_user_id)
        .order_by(Rating.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    ratings = [r.to_dict() for r in pagination.items]

    return jsonify({
        "success": True,
        "ratings": ratings,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }), 200


@ratings_bp.route("/contractor/<contractor_id>", methods=["GET"])
def get_contractor_ratings(contractor_id):
    """
    Return all ratings received by a contractor (i.e. ratings from customers
    on jobs where this contractor was the driver).
    Supports pagination via ?page= and ?per_page= query params.
    """
    contractor = db.session.get(Contractor, contractor_id)
    if not contractor:
        return jsonify({"error": "Contractor not found"}), 404

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    pagination = (
        Rating.query
        .filter_by(to_user_id=contractor.user_id)
        .order_by(Rating.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    ratings = [r.to_dict() for r in pagination.items]

    return jsonify({
        "success": True,
        "contractor_id": contractor_id,
        "avg_rating": contractor.avg_rating,
        "ratings": ratings,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }), 200


@ratings_bp.route("/job/<job_id>", methods=["GET"])
@require_auth
def get_job_rating(user_id, job_id):
    """
    Return the rating for a specific job.
    Only the job's customer or the assigned driver can view it.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Authorization: must be customer or the driver's user
    is_customer = user_id == job.customer_id
    is_driver = False
    if job.driver_id:
        contractor = db.session.get(Contractor, job.driver_id)
        if contractor and contractor.user_id == user_id:
            is_driver = True

    if not is_customer and not is_driver:
        return jsonify({"error": "Not authorized to view this rating"}), 403

    rating = Rating.query.filter_by(job_id=job_id).first()
    if not rating:
        return jsonify({"success": True, "rating": None}), 200

    return jsonify({"success": True, "rating": rating.to_dict()}), 200
