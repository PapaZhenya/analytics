import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { CommentOut } from "@/api/calls";
import { createComment } from "@/api/calls";

export function CommentThread({ callId, comments }: { callId: string; comments: CommentOut[] }) {
  const [body, setBody] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => createComment(callId, { body }),
    onSuccess: () => {
      setBody("");
      queryClient.invalidateQueries({ queryKey: ["call", callId] });
    },
  });

  return (
    <div className="comment-thread">
      <h3>Comments</h3>
      <ul>
        {comments.map((c) => (
          <li key={c.id}>
            <span className="comment-meta">{new Date(c.created_at).toLocaleString()}</span>
            <p>{c.body}</p>
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (body.trim()) mutation.mutate();
        }}
      >
        <input
          placeholder="Add a comment..."
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <button type="submit" disabled={mutation.isPending || !body.trim()}>
          Post
        </button>
      </form>
    </div>
  );
}
