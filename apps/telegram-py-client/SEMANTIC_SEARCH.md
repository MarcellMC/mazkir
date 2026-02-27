# Semantic Search Feature

## Overview

The `/search` command enables semantic search across your stored messages using vector embeddings. Unlike keyword search, semantic search finds messages by **meaning**, not just exact word matches.

## How It Works

1. **Query Processing**: Your search query is converted to a 768-dimensional vector using Ollama's `nomic-embed-text` model
2. **Vector Search**: The system uses pgvector's L2 distance to find the 10 most similar message embeddings
3. **Results**: Messages are ranked by semantic similarity and displayed with dates

## Usage

### Basic Search

```
/search <your query>
```

### Examples

**Find messages about a topic (even with different wording):**
```
/search programming tutorials
→ Finds: "coding courses", "development resources", "learn to code"

/search meeting schedules
→ Finds: "appointment times", "calendar events", "when to meet"

/search Israel travel
→ Finds: "visiting Tel Aviv", "trip to Jerusalem", "Israeli vacation"
```

**Search by concept:**
```
/search cryptocurrency
→ Finds messages about Bitcoin, blockchain, crypto trading, etc.

/search political news
→ Finds articles about government, elections, policy, etc.
```

**Search in any language:**
```
/search обучение (Russian for "education")
→ Finds messages about learning, courses, tutorials in any language
```

## Features

- **Returns top 10 results** ranked by similarity
- **Date-stamped** - Each result shows when the message was saved
- **Preview text** - First 150 characters of each message
- **Multi-language** - Works across Russian, English, Hebrew

## Why Semantic Search is Powerful

### Traditional Keyword Search:
- Query: "python tutorial"
- Finds: Only messages containing "python" AND "tutorial"
- Misses: "learn programming", "coding course", "development guide"

### Semantic Search:
- Query: "python tutorial"
- Finds: Messages about learning programming, coding courses, Python guides, development resources
- Works even if exact words aren't present

## Technical Details

- **Embedding Model**: nomic-embed-text (768 dimensions)
- **Database**: PostgreSQL with pgvector extension
- **Search Algorithm**: L2 distance (Euclidean distance in vector space)
- **Index Type**: IVFFlat for efficient similarity search

## Example Use Cases

1. **Finding Related Content**
   - "Show me everything about machine learning"
   - Even finds "AI models", "neural networks", "deep learning"

2. **Topic Exploration**
   - "What did I save about health?"
   - Finds diet, fitness, medical, wellness messages

3. **Cross-Language Search**
   - Search in English, find results in Russian/Hebrew
   - Embeddings capture meaning regardless of language

4. **Fuzzy Memory**
   - "Something about Israeli tech companies"
   - Finds relevant messages even if you don't remember exact words

## Comparison with Other Commands

| Command | Type | Use Case |
|---------|------|----------|
| `/search` | Semantic | Find by meaning, topic, concept |
| `/analyze` | LLM Analysis | Get insights, patterns, summaries |
| `/sync` | Data Import | Fetch messages from Telegram |

## Performance

- Search typically completes in < 1 second
- Searches all 197 messages with embeddings
- Results ordered by relevance (most similar first)

## Limitations

- Only searches messages that have been synced with `/sync`
- Only searches messages with text (images/videos without captions are skipped)
- Returns maximum 10 results (can be increased in code)

## Tips for Better Results

1. **Be specific but not too narrow**
   - Good: "cryptocurrency trading"
   - Too broad: "technology"
   - Too narrow: "Bitcoin price on December 15th"

2. **Use natural language**
   - Good: "How to learn Hebrew"
   - Also good: "Hebrew language courses"

3. **Try multiple phrasings**
   - If "coding tutorials" doesn't find what you want
   - Try: "programming lessons" or "software development resources"

## Future Enhancements

Possible improvements:
- Filter by date range
- Adjust number of results
- Combine with traditional keyword search
- Search within specific clusters/topics
