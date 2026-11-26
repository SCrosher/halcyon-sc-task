-- 'status' marks tool status lines and holding messages ("Checking your diary…"), so a member's
-- earlier conversations can be given to the model without them.
ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'message' CHECK (kind IN ('message', 'status'));
