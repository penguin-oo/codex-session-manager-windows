package com.penguinoo.codexmobile;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.penguinoo.codexmobile.databinding.ItemRecentSessionBinding;

import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

public final class RecentSessionAdapter extends RecyclerView.Adapter<RecentSessionAdapter.RecentSessionViewHolder> {
    public interface OnSessionClickListener {
        void onSessionClick(SessionSummary session);
    }

    private final List<SessionSummary> items = new ArrayList<>();
    private final OnSessionClickListener listener;
    private final DateFormat dateFormat = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT);

    public RecentSessionAdapter(OnSessionClickListener listener) {
        this.listener = listener;
    }

    public void submitList(List<SessionSummary> sessions) {
        items.clear();
        items.addAll(sessions);
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public RecentSessionViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemRecentSessionBinding binding = ItemRecentSessionBinding.inflate(LayoutInflater.from(parent.getContext()), parent, false);
        return new RecentSessionViewHolder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull RecentSessionViewHolder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    final class RecentSessionViewHolder extends RecyclerView.ViewHolder {
        private final ItemRecentSessionBinding binding;

        RecentSessionViewHolder(ItemRecentSessionBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(SessionSummary session) {
            binding.titleText.setText(SessionCollections.displayTitle(session));
            binding.subtitleText.setText(SessionCollections.primarySubtitle(session));
            binding.metaText.setText(session.timestamp > 0 ? dateFormat.format(new Date(session.timestamp * 1000L)) : "");
            binding.replyingBadgeText.setVisibility(session.isReplying ? View.VISIBLE : View.GONE);
            binding.getRoot().setBackgroundResource(session.isReplying ? R.drawable.bg_card_active : R.drawable.bg_card);
            binding.getRoot().setOnClickListener(view -> listener.onSessionClick(session));
        }
    }
}

