/**
 * Copyright 2025 © BeeAI a Series of LF Projects, LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import type { PropsWithChildren } from 'react';

import classes from './FileCardsList.module.scss';

export function FileCardsList({ children }: PropsWithChildren) {
  return <ul className={classes.root}>{children}</ul>;
}
