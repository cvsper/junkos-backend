"""
Referral API routes for Umuve.
Allows customers to share referral codes and track referral rewards.
"""

from flask import Blueprint, jsonify

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, User, Referral, generate_referral_code
from auth_routes import require_auth

referrals_bp = Blueprint("referrals", __name__, url_prefix="/api/referrals")


@referrals_bp.route("/my-code", methods=["GET"])
@require_auth
def get_my_code(user_id):
    """Get the current user's referral code.

    If the user does not yet have a referral code, generate one.
    """
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Generate referral code on the fly if the user doesn't have one
    if not user.referral_code:
        # Ensure uniqueness
        for _ in range(10):
            code = generate_referral_code()
            existing = User.query.filter_by(referral_code=code).first()
            if not existing:
                user.referral_code = code
                db.session.commit()
                break
        else:
            return jsonify({"error": "Failed to generate unique referral code"}), 500

    return jsonify({
        "success": True,
        "referral_code": user.referral_code,
        "share_url": "/book?ref={}".format(user.referral_code),
    }), 200


@referrals_bp.route("/stats", methods=["GET"])
@require_auth
def get_referral_stats(user_id):
    """Get referral statistics for the current user.

    Returns total referred, completed, and total earned.
    """
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    referrals = Referral.query.filter_by(referrer_id=user_id).all()

    total_referred = len(referrals)
    signed_up = sum(1 for r in referrals if r.status in ("signed_up", "completed", "rewarded"))
    completed = sum(1 for r in referrals if r.status in ("completed", "rewarded"))
    total_earned = sum(r.reward_amount for r in referrals if r.status in ("completed", "rewarded"))

    return jsonify({
        "success": True,
        "stats": {
            "total_referred": total_referred,
            "signed_up": signed_up,
            "completed": completed,
            "total_earned": round(total_earned, 2),
            "reward_per_referral": 10.00,
        },
        "referrals": [r.to_dict() for r in referrals],
    }), 200


@referrals_bp.route("/validate/<code>", methods=["POST"])
def validate_referral_code(code):
    """Validate a referral code and return the referrer's name.

    This endpoint is public (no auth required) so new users can
    verify a referral code before signing up.
    """
    if not code or len(code) != 8:
        return jsonify({"error": "Invalid referral code"}), 400

    referrer = User.query.filter_by(referral_code=code.upper()).first()
    if not referrer:
        return jsonify({"error": "Referral code not found"}), 404

    # Mask the name for privacy (show first name + last initial)
    display_name = referrer.name or "An Umuve user"
    parts = display_name.strip().split()
    if len(parts) >= 2:
        display_name = "{} {}.".format(parts[0], parts[-1][0])
    elif len(parts) == 1:
        display_name = parts[0]

    return jsonify({
        "success": True,
        "referrer_name": display_name,
        "referral_code": referrer.referral_code,
    }), 200
