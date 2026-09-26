import type { IconName } from './components/icons';

export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  /** Shown in the mobile bottom bar; the rest live under "More". */
  primary: boolean;
}

export const NAV: NavItem[] = [
  { href: '/', label: 'Today', icon: 'today', primary: true },
  { href: '/library', label: 'Library', icon: 'library', primary: true },
  { href: '/search', label: 'Search', icon: 'search', primary: true },
  { href: '/tutor', label: 'Tutor', icon: 'tutor', primary: true },
  { href: '/questions', label: 'Questions', icon: 'questions', primary: false },
  { href: '/exams', label: 'Exams', icon: 'exams', primary: false },
  { href: '/viva', label: 'Viva', icon: 'viva', primary: false },
  { href: '/knowledge', label: 'Knowledge', icon: 'knowledge', primary: false },
  { href: '/progress', label: 'Progress', icon: 'progress', primary: false },
  { href: '/settings', label: 'Settings', icon: 'settings', primary: false }
];

export function isActive(href: string, pathname: string): boolean {
  return href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`);
}
