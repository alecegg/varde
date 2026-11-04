export type LoadingView = 'skeleton' | 'content' | 'empty';

/** Keep empty states hidden until the first request settles. */
export function loadingView(loading: boolean, hasData: boolean): LoadingView {
  if (hasData) return 'content';
  return loading ? 'skeleton' : 'empty';
}
