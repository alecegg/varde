export const BACK_BUTTON_SIZE = 44;

export function backButtonGeometry(containerWidth: number, containerHeight: number, iconWidth: number, iconHeight: number) {
  return {
    width: BACK_BUTTON_SIZE,
    height: BACK_BUTTON_SIZE,
    iconLeft: (containerWidth - iconWidth) / 2,
    iconTop: (containerHeight - iconHeight) / 2,
  };
}
