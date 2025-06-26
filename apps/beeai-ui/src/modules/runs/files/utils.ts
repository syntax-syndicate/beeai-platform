/**
 * Copyright 2025 © BeeAI a Series of LF Projects, LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { FILE_CONTENT_URL, FILE_CONTENT_URL_BASE } from './constants';

export function parseFilename(filename: string) {
  const lastDotIndex = filename.lastIndexOf('.');

  if (lastDotIndex === -1) {
    return {
      name: filename,
      ext: '',
    };
  }

  return {
    name: filename.slice(0, lastDotIndex),
    ext: filename.slice(lastDotIndex + 1),
  };
}

export function getFileContentUrl({ id, addBase }: { id: string; addBase?: boolean }) {
  return `${addBase ? FILE_CONTENT_URL_BASE : ''}${FILE_CONTENT_URL.replace('{file_id}', id)}`;
}
