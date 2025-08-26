import json
from functools import wraps
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==============================
# CONFIG (edit as needed)
# ==============================
ACCESS_TOKEN = "mysecrettoken123"   # Token returned by /token and required by data endpoints
CLIENT_ID = "testclient"
CLIENT_SECRET = "testsecret"

# If you want to force-add IsActive + clean dates on GET responses
AUTO_ENSURE_ISACTIVE = True
AUTO_CLEAN_TERMINATION_DATE = True


# ==============================
# AUTH HELPERS
# ==============================
def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1) Prefer Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()

        # 2) Fallback: ?access_token=<token>  (useful for quick browser testing)
        if not token:
            token = request.args.get("access_token")

        if not token:
            return jsonify({"error": "Missing access token"}), 401

        if token != ACCESS_TOKEN:
            return jsonify({"error": "Invalid access token"}), 403

        return f(*args, **kwargs)
    return decorated


# ==============================
# TOKEN ENDPOINT (OAuth2 Client Credentials)
# ==============================
@app.route("/token", methods=["POST","GET"])
def get_token():
    """
    Supports standard OAuth2 client_credentials:
      - Content-Type: application/x-www-form-urlencoded
        client_id=...&client_secret=...&grant_type=client_credentials

      - Or JSON body: {"client_id": "...", "client_secret": "...", "grant_type": "client_credentials"}
    """
    client_id = request.form.get("client_id")
    client_secret = request.form.get("client_secret")
    grant_type = request.form.get("grant_type")

    # Also support JSON for convenience
    if not client_id or not client_secret or not grant_type:
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        client_id = body.get("client_id", client_id)
        client_secret = body.get("client_secret", client_secret)
        grant_type = body.get("grant_type", grant_type)

    if client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
        return jsonify({"error": "Invalid client credentials"}), 401

    if grant_type != "client_credentials":
        return jsonify({"error": "Unsupported grant type"}), 400

    return jsonify({
        "access_token": ACCESS_TOKEN,
        "token_type": "Bearer",
        "expires_in": 3600
    })


# ==============================
# FILE HELPERS
# ==============================
def load_data(filename):
    with open(f"data/{filename}", "r") as f:
        return json.load(f)

def save_data(filename, data):
    with open(f"data/{filename}", "w") as f:
        json.dump(data, f, indent=2)

def extract_entries(obj):
    """
    Returns (entries_list, root_wrapper_key or None)
    - If obj is {"Report_Entry": [...]}, returns (list, "Report_Entry")
    - If obj is a list, returns (list, None)
    """
    if isinstance(obj, dict) and "Report_Entry" in obj and isinstance(obj["Report_Entry"], list):
        return obj["Report_Entry"], "Report_Entry"
    if isinstance(obj, list):
        return obj, None
    # Unknown shape -> normalize to empty list
    return [], None

def rewrap(entries, wrapper_key):
    """Put entries back into the original structure."""
    if wrapper_key:
        return {wrapper_key: entries}
    return entries

def normalize_for_saviynt(entries):
    """
    Minimal cleanup to avoid Saviynt import errors:
      - Ensure Termination_Date is "" (not "NA" / None)
      - Ensure IsActive is present as "true" (string) if missing
    """
    for rec in entries:
        if AUTO_CLEAN_TERMINATION_DATE:
            td = rec.get("Termination_Date")
            if td in (None, "NA"):
                rec["Termination_Date"] = ""
        if AUTO_ENSURE_ISACTIVE:
            if "IsActive" not in rec or rec.get("IsActive") in (None, ""):
                rec["IsActive"] = "true"


# ==============================
# EMPLOYEES (GET/POST/PUT/DELETE)
# ==============================
@app.route("/employees", methods=["GET", "POST"])
@require_token
def employees_handler():
    data = load_data("employees.json")
    entries, wrapper_key = extract_entries(data)

    if request.method == "GET":
        # Clean for Saviynt on GET
        normalize_for_saviynt(entries)
        return jsonify(rewrap(entries, wrapper_key))

    # For POST, append raw payload as-is (assumes same schema as existing records)
    new_item = request.get_json(force=True, silent=True) or {}
    entries.append(new_item)
    save_data("employees.json", rewrap(entries, wrapper_key))
    return jsonify({"message": "Employee added", "data": new_item}), 201


@app.route("/employees/<emp_id>", methods=["PUT", "DELETE"])
@require_token
def employee_update_delete(emp_id):
    data = load_data("employees.json")
    entries, wrapper_key = extract_entries(data)

    # Decide the key field (Worker_ID or employeeID depending on your dataset)
    # Your current dataset uses Worker_ID; keep that as primary key.
    key_name = "Worker_ID"
    updated = False

    if request.method == "PUT":
        payload = request.get_json(force=True, silent=True) or {}
        for rec in entries:
            if str(rec.get(key_name)) == str(emp_id):
                rec.update(payload)
                updated = True
                break
        if updated:
            save_data("employees.json", rewrap(entries, wrapper_key))
            return jsonify({"message": "Employee updated", "data": payload})
        return jsonify({"error": "Not found"}), 404

    # DELETE
    new_entries = [rec for rec in entries if str(rec.get(key_name)) != str(emp_id)]
    if len(new_entries) != len(entries):
        save_data("employees.json", rewrap(new_entries, wrapper_key))
        return jsonify({"message": "Employee deleted"})
    return jsonify({"error": "Not found"}), 404


# ==============================
# CONTRACTORS (GET/POST/PUT/DELETE)
# ==============================
@app.route("/contractors", methods=["GET", "POST"])
@require_token
def contractors_handler():
    data = load_data("contractors.json")
    entries, wrapper_key = extract_entries(data)

    if request.method == "GET":
        normalize_for_saviynt(entries)
        return jsonify(rewrap(entries, wrapper_key))

    new_item = request.get_json(force=True, silent=True) or {}
    entries.append(new_item)
    save_data("contractors.json", rewrap(entries, wrapper_key))
    return jsonify({"message": "Contractor added", "data": new_item}), 201


@app.route("/contractors/<emp_id>", methods=["PUT", "DELETE"])
@require_token
def contractor_update_delete(emp_id):
    data = load_data("contractors.json")
    entries, wrapper_key = extract_entries(data)

    # Choose a key: if your contractors use employeeID or Worker_ID, set it here
    key_candidates = ["employeeID", "Worker_ID", "contractorID"]
    key_name = next((k for k in key_candidates if any(k in rec for rec in entries)), "employeeID")

    if request.method == "PUT":
        payload = request.get_json(force=True, silent=True) or {}
        for rec in entries:
            if str(rec.get(key_name)) == str(emp_id):
                rec.update(payload)
                save_data("contractors.json", rewrap(entries, wrapper_key))
                return jsonify({"message": "Contractor updated", "data": rec})
        return jsonify({"error": "Not found"}), 404

    new_entries = [rec for rec in entries if str(rec.get(key_name)) != str(emp_id)]
    if len(new_entries) != len(entries):
        save_data("contractors.json", rewrap(new_entries, wrapper_key))
        return jsonify({"message": "Contractor deleted"})
    return jsonify({"error": "Not found"}), 404


# ==============================
# CONVERSION (GET/POST/PUT/DELETE)
# ==============================
@app.route("/conversion", methods=["GET", "POST"])
@require_token
def conversion_handler():
    data = load_data("conversion.json")
    entries, wrapper_key = extract_entries(data)

    if request.method == "GET":
        # Return only the fields that exist in JSON
        return jsonify(rewrap(entries, wrapper_key))

    new_item = request.get_json(force=True, silent=True) or {}
    entries.append(new_item)
    save_data("conversion.json", rewrap(entries, wrapper_key))
    return jsonify({"message": "Conversion added", "data": new_item}), 201


@app.route("/conversion/<contractor_id>", methods=["PUT", "DELETE"])
@require_token
def conversion_update_delete(contractor_id):
    data = load_data("conversion.json")
    entries, wrapper_key = extract_entries(data)

    # Typical key for conversion records
    key_candidates = ["contractorID", "Worker_ID", "employeeID"]
    key_name = next((k for k in key_candidates if any(k in rec for rec in entries)), "contractorID")

    if request.method == "PUT":
        payload = request.get_json(force=True, silent=True) or {}
        for rec in entries:
            if str(rec.get(key_name)) == str(contractor_id):
                rec.update(payload)
                save_data("conversion.json", rewrap(entries, wrapper_key))
                return jsonify({"message": "Conversion updated", "data": rec})
        return jsonify({"error": "Not found"}), 404

    new_entries = [rec for rec in entries if str(rec.get(key_name)) != str(contractor_id)]
    if len(new_entries) != len(entries):
        save_data("conversion.json", rewrap(new_entries, wrapper_key))
        return jsonify({"message": "Conversion deleted"})
    return jsonify({"error": "Not found"}), 404


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    # Port 80 works well with `ngrok http 80`
    app.run(host="0.0.0.0", port=80)
