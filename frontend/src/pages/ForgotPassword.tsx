import { useState } from "react";
import { Link } from "react-router-dom";
import { EduAlignLogo } from "../components/EduAlignLogo";
import { postForgotPassword } from "../api";
import { validatePasswordComplexity } from "../utils/passwordValidation";
import "../auth.css";

export function ForgotPassword() {
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    setSuccess(false);

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    const passwordError = validatePasswordComplexity(newPassword);
    if (passwordError) {
      setError(passwordError);
      return;
    }

    setLoading(true);
    try {
      await postForgotPassword(identifier.trim(), email.trim().toLowerCase(), newPassword);
      setSuccess(true);
      setIdentifier("");
      setEmail("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reset password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card auth-card-centered">
        <div style={{ display: "flex", justifyContent: "center", marginBottom: "0.5rem" }}>
          <EduAlignLogo height={48} />
        </div>
        <p className="auth-welcome">Reset your password</p>
        <form className="auth-form" onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="reset-identifier">Username or email</label>
            <input
              id="reset-identifier"
              type="text"
              autoComplete="username"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              placeholder="Enter your username or email"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="reset-email">Account email (for verification)</label>
            <input
              id="reset-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="reset-password">New password</label>
            <input
              id="reset-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Min 8 chars, include upper, lower, number, symbol"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="reset-confirm">Confirm new password</label>
            <input
              id="reset-confirm"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter new password"
              required
            />
          </div>
          {success && (
            <p
              className="auth-success"
              style={{ color: "#15803d", background: "#f0fdf4", padding: "0.75rem 1rem", borderRadius: 8, textAlign: "center" }}
            >
              Password reset successful. You can now sign in.
            </p>
          )}
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" className="auth-btn-primary" disabled={loading}>
            {loading ? "Resetting..." : "Reset Password"}
          </button>
        </form>
        <p className="auth-footer-link" style={{ marginTop: "0.5rem" }}>
          <Link to="/login">Back to Sign in</Link>
        </p>
      </div>
    </div>
  );
}
