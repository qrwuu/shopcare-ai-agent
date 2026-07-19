export interface AuthUser {
  user_id: number;
  username: string;
  full_name: string;
  is_admin: boolean;
}

export interface LoginResponse extends AuthUser {
  access_token: string;
  token_type: "bearer";
}

export interface RegisterResponse extends LoginResponse {}

export interface RegisterInput {
  nickname: string;
  password: string;
}

export interface CurrentUserResponse extends AuthUser {
  email: string;
  phone: string | null;
  created_at: string;
}

export interface StoredAuthState {
  token: string;
  user: AuthUser;
}
