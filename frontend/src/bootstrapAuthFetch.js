/**
 * Imported before the rest of the app: every fetch() to a project API gets
 * authorization and a retry on 401 without importing anything else.
 */
import { installGlobalAuthenticatedFetch } from './utils/api';

installGlobalAuthenticatedFetch();
