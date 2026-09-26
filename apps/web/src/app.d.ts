import type { ThemePref } from '$lib/theme';

declare global {
  namespace App {
    interface Locals {
      user: {
        subject: string;
        name: string;
        email?: string;
        roles: string[];
        tenantId: string;
        tenantRole: string;
      } | null;
      theme: ThemePref;
    }
  }
}

export {};
