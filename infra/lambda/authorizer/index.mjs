import { createHash, timingSafeEqual } from "node:crypto";

/**
 * Lambda authorizer for the HTTP API (simple responses, payload format 2.0): a request is allowed only when its
 * Authorization header is exactly the site password. The password is read through `getPassword()` once and kept for
 * the life of the instance; a failed read is not kept, so the next request tries again. Anything unexpected denies.
 *
 * Both sides are hashed before the constant-time compare so the lengths match and the compare leaks nothing about the
 * password. The header and the password are never logged; a failed read logs only its error message.
 */
export function createHandler({ getPassword }) {
  let cached;
  const password = () => {
    cached ??= getPassword().catch((error) => {
      cached = undefined;
      throw error;
    });
    return cached;
  };
  const digest = (value) => createHash("sha256").update(value).digest();

  return async (event) => {
    try {
      const stored = await password();
      const given = event?.headers?.authorization;
      if (!stored || typeof given !== "string") return { isAuthorized: false };
      return { isAuthorized: timingSafeEqual(digest(given), digest(stored)) };
    } catch (error) {
      console.error(
        `authorizer could not check the password: ${error instanceof Error ? error.message : String(error)}`,
      );
      return { isAuthorized: false };
    }
  };
}

// The AWS SDK comes from the Lambda runtime, so it is loaded here only, never when the module is imported by a test.
let handle;
export const handler = async (event) => {
  handle ??= createHandler({
    getPassword: async () => {
      const { SSMClient, GetParameterCommand } = await import("@aws-sdk/client-ssm");
      const result = await new SSMClient({}).send(
        new GetParameterCommand({ Name: process.env.PASSWORD_PARAMETER, WithDecryption: true }),
      );
      return result.Parameter?.Value;
    },
  });
  return handle(event);
};
