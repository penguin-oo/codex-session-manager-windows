package com.penguinoo.codexmobile;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.penguinoo.codexmobile.databinding.ItemSessionBinding;

import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

public final class SessionListAdapter extends RecyclerView.Adapter<SessionListAdapter.SessionViewHolder> {
    public interface OnSessionClickListener {
        void onSessionClick(SessionSummary session);
    }

    private final List<SessionSummary> items = new ArrayList<>();
    private final OnSessionClickListener listener;
    private final DateFormat dateFormat = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT);

    public SessionListAdapter(OnSessionClickListener listener) {
        this.listener = listener;
    }

    public void submitList(List<SessionSummary> sessions) {
        items.clear();
        items.addAll(sessions);
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public SessionViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemSessionBinding binding = ItemSessionBinding.inflate(LayoutInflater.from(parent.getContext()), parent, false);
        return new SessionViewHolder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull SessionViewHolder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    final class SessionViewHolder extends RecyclerView.ViewHolder {
        private final ItemSessionBinding binding;

        SessionViewHolder(ItemSessionBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(SessionSummary session) {
            binding.titleText.setText(SessionCollections.displayTitle(session));
            binding.cwdText.setText(SessionCollections.primarySubtitle(session));
            String time = session.timestamp > 0 ? dateFormat.format(new Date(session.timestamp * 1000L)) : "-";
            binding.metaText.setText(time + "  |  " + safeValue(session.model, "default"));
            binding.replyingBadgeText.setVisibility(session.isReplying ? View.VISIBLE : View.GONE);
            binding.getRoot().setBackgroundResource(session.isReplying ? R.drawable.bg_card_active : R.drawable.bg_card);
            if (session.note != null && !session.note.isEmpty() && session.cwd != null && !session.cwd.isEmpty()) {
                binding.noteText.setVisibility(View.VISIBLE);
                binding.noteText.setText(session.cwd);
            } else {
                binding.noteText.setVisibility(View.GONE);
                binding.noteText.setText("");
            }
            binding.getRoot().setOnClickListener(view -> listener.onSessionClick(session));
        }

        private String safeValue(String value, String fallback) {
            return value == null || value.isEmpty() ? fallback : value;
        }
    }
}

