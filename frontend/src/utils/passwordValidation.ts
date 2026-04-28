const PASSWORD_REQUIREMENTS =
  "Password must be at least 8 characters; include at least one uppercase letter, one lowercase letter, one digit, and one special character (!@#$%^&*(),.?\":{}|<>).";

export function validatePasswordComplexity(password: string): string | null {
  if (password.length < 8) return PASSWORD_REQUIREMENTS;
  if (!/[A-Z]/.test(password)) return PASSWORD_REQUIREMENTS;
  if (!/[a-z]/.test(password)) return PASSWORD_REQUIREMENTS;
  if (!/\d/.test(password)) return PASSWORD_REQUIREMENTS;
  if (!/[!@#$%^&*(),.?":{}|<>_\-+=\[\];/\\'`~]/.test(password)) return PASSWORD_REQUIREMENTS;
  return null;
}
