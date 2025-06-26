/**
 * Copyright 2025 © BeeAI a Series of LF Projects, LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import type { Role } from '../types';

interface Message {
  key: string;
  role: Role;
  content: string;
  error?: unknown;
  files?: MessageFile[];
}
export interface UserMessage extends Message {
  role: Role.User;
}
export interface AssistantMessage extends Message {
  role: Role.Assistant;
  status: MessageStatus;
}

export interface MessageFile {
  key: string;
  filename: string;
  href: string;
}

export type ChatMessage = UserMessage | AssistantMessage;

export enum MessageStatus {
  InProgress = 'in-progress',
  Completed = 'completed',
  Aborted = 'aborted',
  Failed = 'failed',
}
