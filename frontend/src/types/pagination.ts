export type PageInfo = {
  limit: number;
  hasNextPage: boolean;
  nextCursor: string | null;
};

export type CursorPage<T> = {
  data: T[];
  pageInfo: PageInfo;
};

export type ListQueryState = {
  limit: number;
  cursor?: string | null;
  sortKey: string;
  sortDir: "asc" | "desc";
  search?: string;
  status?: string;
};
