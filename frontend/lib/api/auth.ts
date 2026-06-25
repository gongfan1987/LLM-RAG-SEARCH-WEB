import { apiFetch } from "@/lib/api/client";
import type {
  AuthResponse,
  ChangePasswordPayload,
  LoginPayload,
  RegisterPayload,
  User,
} from "@/types/auth";

export function login(payload: LoginPayload): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function register(payload: RegisterPayload): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchCurrentUser(): Promise<User> {
  return apiFetch<User>("/api/auth/me");
}

export function changePassword(
  payload: ChangePasswordPayload
): Promise<void> {
  return apiFetch<void>("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
