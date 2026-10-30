from flask import current_app, render_template


def register_template_helpers(app, sports):
    @app.context_processor
    def inject_globals():
        return {"SPORTS": sports, "SITE_NAME": current_app.config["SITE_NAME"]}

    @app.template_filter("signed")
    def signed(value):
        try:
            return f"{int(value):+d}"
        except (TypeError, ValueError):
            return value

    @app.template_filter("ordinal")
    def ordinal(n):
        n = int(n)
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    @app.template_filter("stat")
    def stat(value, rules, key):
        return rules.fmt(key, value)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404
