declare global {
  namespace App {
    interface Platform {
      readContext?: import("./lib/server/search-reader").SearchReadContext;
      env: {
        DB: D1Database;
        D1_READ_MODE?: "primary" | "session";
        D1_QUERY_LOGS?: "0" | "1";
        SITE_COMMIT?: string;
        DATA_PROJECTION?: string;
        DEPLOYED_AT?: string;
        ASSETS: Fetcher;
      };
      context: ExecutionContext;
    }
  }
}
export {};
